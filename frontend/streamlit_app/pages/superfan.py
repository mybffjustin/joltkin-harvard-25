# frontend/streamlit_app/pages/superfan.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Streamlit page: Superfan Pass

Purpose
-------
Operator-focused UI for interacting with the "Superfan" PyTeal application.
Supports:
  • Discovering the most-recent Superfan app created by the admin
  • One-click deployment of a new Superfan app
  • Buyer/user opt-in to the app
  • Admin awarding points to a target account
  • Buyer claiming a tier once threshold is met
  • Viewing a simple leaderboard pulled from the Indexer

Design Notes
------------
- Contracts are compiled on the fly during deployment to match the current code
  checked into backend/contracts/superfan_pass.py. This avoids drift between the
  demo UI and the source-of-truth contract code.
- Indexer usage is optional. If not configured, leaderboard UI is disabled with
  a clear message.
- Transaction-building uses algosdk v2. Grouping is not required for these flows.
- Streamlit session_state is used to persist the selected/created app id (SF_APP_ID)
  across reruns.

Security
--------
This page handles mnemonics in-memory only (via Streamlit inputs in the sidebar).
They should be **TestNet only**. Do not use production secrets here.

Error Handling
--------------
All network calls are wrapped in try/except blocks and surfaced to the operator
via st.error(). Messages are kept concise and actionable.
"""

import streamlit as st
from algosdk import mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import wait_for_confirmation

from core.clients import get_algod, get_indexer
from services.algorand import read_points_via_indexer
from ui.components import table_ranked_wallets


def render(ctx: dict) -> None:
    """Render the Superfan Pass tab.

    Args:
        ctx: A context dict produced by the sidebar that contains derived values
            like addresses and mnemonics:
              - ctx["admin_addr"], ctx["admin_mn"]
              - ctx["buyer_addr"], ctx["buyer_mn"]
            Presence/absence of these values is used to enable/disable actions.
    """
    st.header("Superfan Pass")

    # Lazily instantiate SDK clients; cached by core.clients via Streamlit's
    # resource cache for performance across reruns.
    c = get_algod()
    idx = get_indexer()
    ss = st.session_state

    # ─────────────────────────────────────────────────────────────────────
    # Quick helpers row
    # ─────────────────────────────────────────────────────────────────────
    col = st.columns(3)

    # Helper: Load the most recently created Superfan app for the admin address
    with col[0]:
        if st.button(
            "Use Last Superfan (admin)",
            disabled=not ctx["admin_addr"],
            use_container_width=True,
        ):
            try:
                # Fetch all apps created by this admin; pick the newest.
                info = c.account_info(ctx["admin_addr"])
                apps = sorted(info.get("created-apps", []), key=lambda a: a["id"])
                app_id = None

                # Heuristic: detect Superfan app by the presence of the "admin"
                # key in global state (as defined by the PyTeal contract).
                for app in reversed(apps):
                    keys = set()
                    for kv in app.get("params", {}).get("global-state", []):
                        import base64

                        try:
                            keys.add(base64.b64decode(kv["key"]).decode())
                        except Exception:
                            # If a key can't be decoded to UTF-8, ignore it.
                            pass
                    if {"admin"}.issubset(keys):
                        app_id = app["id"]
                        break

                if app_id:
                    ss["SF_APP_ID"] = int(app_id)
                    st.success(f"Loaded Superfan App #{app_id}")
                else:
                    st.info("No Superfan apps for this admin.")

            except Exception as e:
                st.error(f"Failed: {e}")

    # Helper: Opt-in the demo "buyer" account to the current Superfan app
    with col[1]:
        if st.button(
            "Buyer Opt-in (quick)",
            disabled=not (ctx["buyer_mn"] and ss.get("SF_APP_ID")),
            use_container_width=True,
        ):
            try:
                sp = c.suggested_params()
                # Standard opt-in: ApplicationOptInTxn
                txid = c.send_transaction(
                    ftxn.ApplicationOptInTxn(
                        sender=ctx["buyer_addr"], sp=sp, index=int(ss["SF_APP_ID"])
                    ).sign(mnemonic.to_private_key(ctx["buyer_mn"]))
                )
                wait_for_confirmation(c, txid, 4)
                st.success("Buyer opted-in")
            except Exception as e:
                st.error(f"Opt-in failed: {e}")

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────
    # Deploy / Use two-column layout
    # ─────────────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    # Left: One-click deploy
    with col1:
        st.subheader("Deploy")

        if st.button(
            "Deploy Superfan (1-click)",
            disabled=not ctx["admin_mn"],
            use_container_width=True,
        ):
            try:
                # Compile PyTeal from the project file dynamically to ensure we're
                # deploying the code that's in-tree.
                import base64
                import importlib.util
                import pathlib

                # Locate the PyTeal contract file relative to this page.
                # pages/ → streamlit_app/ → backend/contracts/superfan_pass.py
                p = (
                    pathlib.Path(__file__).resolve().parents[2]
                    / "contracts"
                    / "superfan_pass.py"
                )
                spec = importlib.util.spec_from_file_location("superfan", str(p))
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)  # type: ignore[union-attr]

                # Compile to TEAL source (approval/clear) targeting AVM v8
                from pyteal import Mode, compileTeal

                ap_teal = compileTeal(m.approval(), Mode.Application, version=8)
                cl_teal = compileTeal(m.clear(), Mode.Application, version=8)

                # Ask Algod to assemble TEAL → bytecode
                comp_ap = c.compile(ap_teal)
                comp_cl = c.compile(cl_teal)
                ap_prog = base64.b64decode(comp_ap["result"])
                cl_prog = base64.b64decode(comp_cl["result"])

                # Create application with the expected state schema:
                #   Global: 0 uints, 2 bytes (admin + ?)
                #   Local:  2 uints, 0 bytes (points, tier)
                sp = c.suggested_params()
                txn = ftxn.ApplicationCreateTxn(
                    sender=ctx["admin_addr"],
                    sp=sp,
                    on_complete=ftxn.OnComplete.NoOpOC,
                    approval_program=ap_prog,
                    clear_program=cl_prog,
                    global_schema=ftxn.StateSchema(0, 2),
                    local_schema=ftxn.StateSchema(2, 0),
                    # The contract expects the admin address as an arg to set global admin
                    app_args=[ctx["admin_addr"].encode()],
                )

                txid = c.send_transaction(
                    txn.sign(mnemonic.to_private_key(ctx["admin_mn"]))
                )
                resp = wait_for_confirmation(c, txid, 4)
                ss["SF_APP_ID"] = int(resp["application-index"])
                st.success(f"✅ Superfan App ID: {ss['SF_APP_ID']}")

            except Exception as e:
                st.error(f"Deploy Superfan failed: {e}")

    # Right: Operate against an existing app (opt-in, add points, claim tier)
    with col2:
        st.subheader("Use")

        # Keep the app id in session so it's reused across UI actions
        sf_app = st.number_input(
            "Superfan App ID", min_value=0, step=1, value=int(ss.get("SF_APP_ID", 0))
        )
        ss["SF_APP_ID"] = int(sf_app)

        # Default parameters for add_points / claim_tier actions
        points = st.number_input("Points to add", min_value=1, step=1, value=10)
        tier_threshold = st.number_input(
            "Tier threshold", min_value=1, step=1, value=100
        )

        row = st.columns(3)

        # Buyer opt-in
        with row[0]:
            if st.button(
                "Opt-in (Buyer)",
                disabled=not (ctx["buyer_mn"] and sf_app),
                use_container_width=True,
            ):
                try:
                    sp = c.suggested_params()
                    txid = c.send_transaction(
                        ftxn.ApplicationOptInTxn(
                            sender=ctx["buyer_addr"], sp=sp, index=int(sf_app)
                        ).sign(mnemonic.to_private_key(ctx["buyer_mn"]))
                    )
                    wait_for_confirmation(c, txid, 4)
                    st.success("✅ Opt-in OK")
                except Exception as e:
                    st.error(f"Opt-in failed: {e}")

        # Admin → add points to a specific account (buyer by default)
        with row[1]:
            if st.button(
                "Admin → Add Points",
                disabled=not (ctx["admin_mn"] and ctx["buyer_addr"] and sf_app),
                use_container_width=True,
            ):
                try:
                    sp = c.suggested_params()
                    # Flat fee often preferred for predictable costs; single inner-logic
                    # no-ops typically fit within 1000 µAlgos.
                    sp.flat_fee = True
                    sp.fee = 1000

                    # Contract expects:
                    #   app_args[0] = b"add_points"
                    #   app_args[1] = amount (big-endian uint64)
                    #   accounts[0] = target account to credit
                    tx = ftxn.ApplicationNoOpTxn(
                        sender=ctx["admin_addr"],
                        sp=sp,
                        index=int(sf_app),
                        app_args=[b"add_points", int(points).to_bytes(8, "big")],
                        accounts=[ctx["buyer_addr"]],
                    )
                    txid = c.send_transaction(
                        tx.sign(mnemonic.to_private_key(ctx["admin_mn"]))
                    )
                    wait_for_confirmation(c, txid, 4)
                    st.success("✅ Points added")
                except Exception as e:
                    st.error(f"Add points failed: {e}")

        # Buyer → claim tier once threshold met
        with row[2]:
            if st.button(
                "Buyer → Claim Tier",
                disabled=not (ctx["buyer_mn"] and sf_app),
                use_container_width=True,
            ):
                try:
                    sp = c.suggested_params()
                    # Contract expects:
                    #   app_args[0] = b"claim_tier"
                    #   app_args[1] = threshold (big-endian uint64)
                    txid = c.send_transaction(
                        ftxn.ApplicationNoOpTxn(
                            sender=ctx["buyer_addr"],
                            sp=sp,
                            index=int(sf_app),
                            app_args=[
                                b"claim_tier",
                                int(tier_threshold).to_bytes(8, "big"),
                            ],
                        ).sign(mnemonic.to_private_key(ctx["buyer_mn"]))
                    )
                    wait_for_confirmation(c, txid, 4)
                    st.success("✅ Tier claimed")
                except Exception as e:
                    st.error(f"Claim tier failed: {e}")

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────
    # Leaderboard (via Indexer)
    # ─────────────────────────────────────────────────────────────────────
    st.subheader("Leaderboard")

    if idx:
        # Pull top accounts by points for the current app id; simple server-side
        # refresh button triggers the query and table render.
        if st.button(
            "Refresh Top Wallets",
            disabled=not ss.get("SF_APP_ID"),
            use_container_width=True,
        ):
            try:
                rows = read_points_via_indexer(idx, int(ss["SF_APP_ID"]))
                if rows:
                    # Render a compact ranked table; function abstracts formatting.
                    table_ranked_wallets(rows[:20])
                else:
                    st.info("No accounts found for this app yet.")
            except Exception as e:
                st.error(f"Leaderboard error: {e}")
    else:
        # If Indexer is not configured, guide the operator to set it up.
        st.info("Indexer not configured. Set INDEXER_URL in .env.")
