# frontend/streamlit_app/pages/trade.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Streamlit page: Buy / Resale

Purpose
-------
Operator-facing flows to demonstrate primary sales and secondary (resale)
transactions for a Ticket ASA coordinated by a PyTeal "Royalty Router"
application. This page intentionally favors clarity and guardrails over
feature breadth so it's safe to demo live on TestNet.

What this page can do
---------------------
• Discover the most recent Router app created by the configured creator.
• Help a Buyer opt in to the Ticket ASA (prerequisite for receiving tokens).
• Run a **Primary Buy**: buyer pays the Router; seller transfers 1 ASA unit;
  Router performs inner payments to split the primary revenue.
• Run a **Resale**: new buyer pays the Router; holder transfers the ASA unit;
  Router pays artist royalty + remainder to the holder.

Safety / UX notes
-----------------
• All actions validate minimum balances, ASA opt-ins, and router global state.
• Buttons are disabled until preconditions are met.
• App call fees are set with `flat_fee` to reliably cover inner transactions.

Implementation highlights
-------------------------
• We build three transactions and group them atomically:
  [ApplicationCall, Payment, AssetTransfer]
• Router global state is read once and validated before any spend.
• Widget keys are namespaced via `ui.keys.k()` to avoid duplicate IDs across tabs.
"""

# --- make local packages importable (ui/, pages/, core/, services/) ----------
# This keeps relative imports robust when Streamlit changes the working dir.
import pathlib
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
# -----------------------------------------------------------------------------


import streamlit as st
from algosdk import mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import logic, wait_for_confirmation

from core.clients import get_algod
from core.constants import APP_CALL_INNER_FEE, MIN_BALANCE
from services.algorand import (
    addr_from_mn,
    algo_balance,
    asset_balance,
    is_opted_in,
    read_router_globals,
)
from ui.keys import k

# ============================== Helper functions =============================


def _load_last_router_id(c, creator_addr: str | None) -> int | None:
    """Return the most recent Router application ID created by `creator_addr`.

    Heuristic:
      - Scan "created-apps" for the creator.
      - Decode global-state keys; consider it a "Router" if it exposes the
        expected keys: p1/p2/p3 + bps1/bps2/bps3.
      - Return the most recent match (highest app id).

    Args:
        c: An initialized `algosdk.v2client.algod.AlgodClient`.
        creator_addr: Base32 Algorand address of the creator.

    Returns:
        The integer app id if found, else None.
    """
    if not creator_addr:
        return None
    try:
        info = c.account_info(creator_addr)
        apps = sorted(info.get("created-apps", []), key=lambda a: a["id"])
        for app in reversed(apps):
            keys = set()
            for kv in app.get("params", {}).get("global-state", []):
                # Keys are base64-encoded; decode best-effort.
                import base64

                try:
                    keys.add(base64.b64decode(kv["key"]).decode())
                except Exception:
                    # Ignore undecodable keys; we're only sniffing for known names.
                    pass
            if {"p1", "p2", "p3", "bps1", "bps2", "bps3"}.issubset(keys):
                return int(app["id"])
    except Exception:
        # Swallow and return None so the UI can show a friendly message.
        pass
    return None


def _router_and_asa_inputs(ss) -> tuple[int, int, int]:
    """Render page-level inputs (Router App ID, Ticket ASA ID, price) and persist.

    These inputs are shared by both "Primary Buy" and "Resale" panels.
    Values persist in `st.session_state` to enable cross-tab reuse.

    Args:
        ss: Streamlit session_state (dict-like)

    Returns:
        Tuple of (app_id, asa_id, price) as integers.
    """
    app_id = st.number_input(
        "Router App ID",
        min_value=0,
        step=1,
        value=int(ss.get("TRADE_APP_ID", 0)),
        key=k("trade", "router_app_id"),
    )
    asa_id = st.number_input(
        "Ticket ASA ID",
        min_value=0,
        step=1,
        value=int(ss.get("TRADE_ASA_ID", 0)),
        key=k("trade", "ticket_asa_id"),
    )
    price = st.number_input(
        "Price (µAlgos)",
        min_value=0,
        step=1_000,
        value=int(ss.get("TRADE_PRICE", 1_000_000)),
        key=k("trade", "price_microalgos"),
        help="Total µAlgos the buyer/new buyer pays to the Router application.",
    )

    # Persist for this session; other tabs may pick these up.
    ss["TRADE_APP_ID"], ss["TRADE_ASA_ID"], ss["TRADE_PRICE"] = (
        int(app_id),
        int(asa_id),
        int(price),
    )
    return int(app_id), int(asa_id), int(price)


def _guard_router_globals_valid(globals_: dict, needs_seller: bool = True) -> None:
    """Validate Router global state contains payout addresses (and seller when needed).

    Args:
        globals_: Dict returned by `services.algorand.read_router_globals()`.
        needs_seller: When True, also require a valid `seller` address (primary buy).

    Raises:
        RuntimeError: If any required address is missing or malformed.
    """
    req = ["p1", "p2", "p3"] + (["seller"] if needs_seller else [])
    addrs = [globals_.get(x) for x in req]
    if not all(isinstance(a, str) and len(a) == 58 for a in addrs):
        missing = [
            r
            for r, a in zip(req, addrs, strict=False)
            if not (isinstance(a, str) and len(a) == 58)
        ]
        raise RuntimeError(f"Router globals missing/invalid: {', '.join(missing)}.")


# ============================== Main render ==================================


def render(ctx: dict) -> None:
    """Render the Buy / Resale tab.

    `ctx` is produced by the sidebar and typically contains:
      - creator_addr / creator_mn
      - seller_addr / seller_mn
      - buyer_addr  / buyer_mn
      - admin_addr  / admin_mn
      - (optional) bank_mn
    """
    st.header("Buy / Resale")

    # Initialize algod client once (cached by core.clients).
    c = get_algod()
    ss = st.session_state

    col = st.columns(3)

    # -- Discover the most recent Router owned by the creator ------------------
    with col[0]:
        if st.button(
            "Use Last Router (creator)",
            disabled=not ctx["creator_addr"],
            use_container_width=True,
            key=k("trade", "use_last_router"),
        ):
            app_id = _load_last_router_id(c, ctx["creator_addr"])
            if not app_id:
                st.info("No Router apps found for this creator.")
            else:
                ss["TRADE_APP_ID"] = int(app_id)
                try:
                    gs = read_router_globals(c, int(app_id))
                    if isinstance(gs.get("asa"), int):
                        ss["TRADE_ASA_ID"] = int(gs["asa"])
                    st.success(f"Loaded Router #{app_id} (ASA {gs.get('asa', '—')})")
                except Exception:
                    # Even if globals read fails, we still surfaced the app id.
                    st.success(f"Loaded Router #{app_id}")

    # -- Quick buyer opt-in to the Ticket ASA (prerequisite to receive ASA) ----
    with col[1]:
        if st.button(
            "Buyer Opt-in to ASA",
            disabled=not (
                ctx["buyer_mn"] and ctx["buyer_addr"] and ss.get("TRADE_ASA_ID")
            ),
            use_container_width=True,
            key=k("trade", "buyer_optin"),
        ):
            try:
                sp = c.suggested_params()
                tx = ftxn.AssetOptInTxn(ctx["buyer_addr"], sp, int(ss["TRADE_ASA_ID"]))
                txid = c.send_transaction(
                    tx.sign(mnemonic.to_private_key(ctx["buyer_mn"]))
                )
                wait_for_confirmation(c, txid, 4)
                st.success(f"Buyer opted-in: {txid}")
            except Exception as e:
                st.error(f"Opt-in failed: {e}")

    # Reserve right column for future quick tools.
    with col[2]:
        st.empty()

    st.markdown("---")

    # Shared inputs: Router ID, ASA ID, price
    app_id, asa_id, price = _router_and_asa_inputs(ss)

    colA, colB = st.columns(2)

    # =============================== Primary Buy ==============================
    with colA:
        st.subheader("Primary Buy")

        # Basic precondition checks to avoid building transactions that will fail.
        buy_disabled = not (
            ctx["buyer_mn"]
            and ctx["seller_mn"]
            and int(app_id) > 0
            and int(asa_id) > 0
            and int(price) > 0
        )
        if st.button(
            "Run Buy (1-click)",
            disabled=buy_disabled,
            use_container_width=True,
            key=k("trade", "buy_run"),
        ):
            try:
                # Read & validate Router global state (payout addresses + seller).
                accs = read_router_globals(c, int(app_id))
                _guard_router_globals_valid(accs, needs_seller=True)
                p1_gs, p2_gs, p3_gs, seller_gs = (
                    accs["p1"],
                    accs["p2"],
                    accs["p3"],
                    accs["seller"],
                )

                # Suggested params for each txn.
                # AppCall must cover inner transactions via flat fee.
                sp0 = c.suggested_params()
                sp0.flat_fee = True
                sp0.fee = APP_CALL_INNER_FEE
                sp1 = c.suggested_params()
                sp2 = c.suggested_params()

                # Guardrails: balances and opt-ins.
                if algo_balance(c, ctx["buyer_addr"]) < (
                    int(price) + MIN_BALANCE + 5_000
                ):
                    raise RuntimeError("Buyer underfunded. Faucet or 'Top up' first.")
                if not is_opted_in(c, ctx["buyer_addr"], int(asa_id)):
                    raise RuntimeError("Buyer not opted-in to ASA.")
                if not is_opted_in(c, ctx["seller_addr"], int(asa_id)):
                    raise RuntimeError("Seller not opted-in to ASA (or no holding).")

                # Transactions for the atomic group:
                # 1) AppCall "buy"       (sender = Buyer)
                # 2) Payment price → app (sender = Buyer)
                # 3) ASA xfer            (sender = Seller → Buyer)
                app_call = ftxn.ApplicationNoOpTxn(
                    sender=ctx["buyer_addr"],
                    sp=sp0,
                    index=int(app_id),
                    app_args=[b"buy"],
                    accounts=[p1_gs, p2_gs, p3_gs, seller_gs],
                )
                app_addr = logic.get_application_address(int(app_id))
                pay = ftxn.PaymentTxn(
                    sender=ctx["buyer_addr"],
                    sp=sp1,
                    receiver=app_addr,
                    amt=int(price),
                )
                asa_txn = ftxn.AssetTransferTxn(
                    sender=ctx["seller_addr"],
                    sp=sp2,
                    receiver=ctx["buyer_addr"],
                    amt=1,
                    index=int(asa_id),
                )

                # Group and sign in the correct order.
                gid = ftxn.calculate_group_id([app_call, pay, asa_txn])
                for t in (app_call, pay, asa_txn):
                    t.group = gid

                txid = c.send_transactions(
                    [
                        app_call.sign(mnemonic.to_private_key(ctx["buyer_mn"])),
                        pay.sign(mnemonic.to_private_key(ctx["buyer_mn"])),
                        asa_txn.sign(mnemonic.to_private_key(ctx["seller_mn"])),
                    ]
                )
                resp = wait_for_confirmation(c, txid, 4)
                st.success(f"✅ Buy OK: {txid} | Round {resp['confirmed-round']}")
            except Exception as e:
                st.error(f"Buy failed: {e}")

    # ================================= Resale =================================
    with colB:
        st.subheader("Resale (holder → new buyer)")

        # The resale flow uses two mnemonics provided ad-hoc:
        # - holder_mn: current owner of the ASA unit
        # - newbuyer_mn: the new buyer
        holder_mn = st.text_input(
            "Holder mnemonic (current owner)",
            "",
            type="password",
            key=k("trade", "holder_mn"),
        )
        newbuyer_mn = st.text_input(
            "New buyer mnemonic",
            "",
            type="password",
            key=k("trade", "newbuyer_mn"),
        )

        holder_addr = addr_from_mn(holder_mn) if holder_mn else None
        newbuyer_addr = addr_from_mn(newbuyer_mn) if newbuyer_mn else None

        # Helper: opt-in the new buyer to the ASA.
        if st.button(
            "Opt-in New Buyer to ASA",
            disabled=not (newbuyer_mn and newbuyer_addr and int(asa_id) > 0),
            use_container_width=True,
            key=k("trade", "newbuyer_optin"),
        ):
            try:
                sp = c.suggested_params()
                txid = c.send_transaction(
                    ftxn.AssetOptInTxn(newbuyer_addr, sp, int(asa_id)).sign(
                        mnemonic.to_private_key(newbuyer_mn)
                    )
                )
                wait_for_confirmation(c, txid, 4)
                st.success(f"New buyer opted-in: {txid}")
            except Exception as e:
                st.error(f"Opt-in failed: {e}")

        resale_disabled = not (
            holder_mn
            and newbuyer_mn
            and int(app_id) > 0
            and int(asa_id) > 0
            and int(price) > 0
        )
        if st.button(
            "Run Resale (1-click)",
            disabled=resale_disabled,
            use_container_width=True,
            key=k("trade", "resale_run"),
        ):
            try:
                if not holder_addr or not newbuyer_addr:
                    raise RuntimeError("Missing holder/new buyer address.")

                # Read & validate Router globals (only payout addresses required).
                accs = read_router_globals(c, int(app_id))
                _guard_router_globals_valid(accs, needs_seller=False)
                p1_gs, p2_gs, p3_gs = accs["p1"], accs["p2"], accs["p3"]

                # App call must cover inner transactions via flat fee.
                sp0 = c.suggested_params()
                sp0.flat_fee = True
                sp0.fee = 3_000  # typical cost; adjust if router changes
                sp1 = c.suggested_params()
                sp2 = c.suggested_params()

                # Guardrails: balances and opt-ins.
                if algo_balance(c, newbuyer_addr) < (int(price) + MIN_BALANCE + 5_000):
                    raise RuntimeError("New buyer underfunded.")
                if not is_opted_in(c, newbuyer_addr, int(asa_id)):
                    raise RuntimeError("New buyer not opted-in to ASA.")
                if asset_balance(c, holder_addr, int(asa_id)) < 1:
                    raise RuntimeError("Holder does not own the ticket.")

                # Transactions for the atomic resale group:
                # 1) AppCall "resale"        (sender = New Buyer)
                # 2) Payment price → app     (sender = New Buyer)
                # 3) ASA xfer                (sender = Holder → New Buyer)
                app_call = ftxn.ApplicationNoOpTxn(
                    sender=newbuyer_addr,
                    sp=sp0,
                    index=int(app_id),
                    app_args=[b"resale"],
                    accounts=[p1_gs, p2_gs, p3_gs, holder_addr],
                )
                app_addr = logic.get_application_address(int(app_id))
                pay = ftxn.PaymentTxn(
                    sender=newbuyer_addr,
                    sp=sp1,
                    receiver=app_addr,
                    amt=int(price),
                )
                asa_txn = ftxn.AssetTransferTxn(
                    sender=holder_addr,
                    sp=sp2,
                    receiver=newbuyer_addr,
                    amt=1,
                    index=int(asa_id),
                )

                # Group, sign by respective parties, submit, and wait.
                gid = ftxn.calculate_group_id([app_call, pay, asa_txn])
                for t in (app_call, pay, asa_txn):
                    t.group = gid

                txid = c.send_transactions(
                    [
                        app_call.sign(mnemonic.to_private_key(newbuyer_mn)),
                        pay.sign(mnemonic.to_private_key(newbuyer_mn)),
                        asa_txn.sign(mnemonic.to_private_key(holder_mn)),
                    ]
                )
                resp = wait_for_confirmation(c, txid, 4)
                st.success(f"✅ Resale OK: {txid} | Round {resp['confirmed-round']}")
            except Exception as e:
                st.error(f"Resale failed: {e}")
