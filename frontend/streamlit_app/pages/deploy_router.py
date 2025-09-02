# frontend/streamlit_app/pages/deploy_router.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Streamlit page: **Deploy Royalty Router**

This page provides two operator-facing flows:

1) **QuickStart (1-click)** — For demos. Mints a whole-number Ticket ASA,
   deploys the Royalty Router PyTeal app with payout splits + resale royalty,
   and surfaces the resulting identifiers to the operator.

2) **Advanced Router Settings** — For precise configuration. Lets the
   operator specify an existing Ticket ASA, payout addresses, split bps,
   and royalty bps, then deploys the Router.

Design goals
------------
- Keep deployment **stateless** and focused. We intentionally *do not* perform
  buyer/seller opt-ins or app prefunding here; those flows live on the Trade
  page so responsibilities are clear and failures are easier to localize.
- Avoid surprises. Inputs are prefilled from sensible defaults (env/settings,
  or addresses present in the sidebar context) but can be overridden at any
  time.
- Graceful failure. All network calls are wrapped and user-visible messages
  are specific and actionable.

Operational notes
-----------------
- This page relies on services provided by `services.algorand` to interact
  with Algod and encapsulate mint/deploy logic.
- Address validation here is deliberately *lightweight* (length check only).
  Robust validation should occur inside the underlying services and contracts.
"""

# Standard library
import base64  # noqa: F401  # Unused; kept if future TEAL debug is added
import pathlib  # noqa: F401  # Unused; kept if future file IO is added

# Third-party
import streamlit as st

# Local modules
from core.clients import get_algod
from core.config import settings
from services.algorand import (
    Funder,  # noqa: F401
    available_funders,
    create_demo_ticket_asa_auto,
    deploy_router_app,
    ensure_funds,  # noqa: F401
    pick_best_funder,  # noqa: F401
    read_router_globals,  # noqa: F401  # Not used directly on this page; useful during future UX tweaks
)

# NOTE: The code references `logic.get_application_address(...)` in a success
# message below, but `logic` is not imported here. If you want the address
# to display, import as:
#   from algosdk.transaction import logic
# We keep the code as-is to preserve module boundaries; see comment at call site.


def render(ctx: dict) -> None:
    """Render the Royalty Router deployment page.

    Args:
        ctx: Context dictionary prepared by the sidebar. Expected keys include:
             - "creator_addr": str | None
             - "creator_mn":  str | None
             - "seller_addr": str | None
             - "seller_mn":   str | None
             - "admin_addr":  str | None
             - "admin_mn":    str | None
             - "buyer_mn":    str | None
             - "bank_mn":     str | None (optional funder for MBR/fees)

    Side effects:
        - Updates `st.session_state`:
          * DEPLOY_ASA_ID: int
          * TRADE_ASA_ID:  int
          * TRADE_APP_ID:  int
        - Emits Streamlit UI elements and status messages.

    This function is idempotent with respect to UI; pressing buttons performs
    network operations which are, by nature, non-idempotent.
    """
    st.header("Deploy Royalty Router")

    # Cached Algod client (see core/clients.py for cache semantics).
    c = get_algod()
    ss = st.session_state

    # ──────────────────────────────────────────────────────────────────────
    # QuickStart: opinionated, fast path for demo setups
    # ──────────────────────────────────────────────────────────────────────
    st.subheader("QuickStart (1-click)")
    colL, colR = st.columns(2)

    # Left column: ticket + economics config
    with colL:
        # Ticket ASA mint parameters (whole-number tickets; decimals handled by create_demo_ticket_asa_auto)
        qs_unit = st.text_input("Ticket unit", value="TIX")
        qs_name = st.text_input("Ticket name", value="TDM Demo Ticket")
        qs_total = st.number_input("Total supply", min_value=1, step=1, value=1000)

        # Split proportions (basis points) for primary sale
        bps1 = st.number_input(
            "Split bps #1 (artist)", min_value=0, max_value=10_000, value=7_000
        )
        bps2 = st.number_input(
            "Split bps #2", min_value=0, max_value=10_000, value=2_500
        )
        bps3 = st.number_input("Split bps #3", min_value=0, max_value=10_000, value=500)

        # Resale royalty (basis points) paid to artist (p1) on secondary sales
        roy_bps = st.number_input(
            "Resale artist royalty bps", min_value=0, max_value=10_000, value=500
        )

    # Right column: payout addresses / primary seller
    with colR:
        # Default payout addresses pull from environment-backed settings first,
        # then fall back to addresses present in the sidebar context.
        default_p1 = settings.ARTIST_ADDR or (ctx["creator_addr"] or "")
        default_p2 = settings.SELLER_ADDR_PREF or (ctx["seller_addr"] or "")
        default_p3 = settings.ADMIN_ADDR_PREF or (ctx["admin_addr"] or "")
        default_seller = settings.SELLER_ADDR_PREF or (ctx["seller_addr"] or "")

        p1 = st.text_input("Payout #1 address (artist)", value=default_p1)
        p2 = st.text_input("Payout #2 address", value=default_p2)
        p3 = st.text_input("Payout #3 address", value=default_p3)
        primary_seller = st.text_input("Primary seller address", value=default_seller)
        st.caption("Prefilled from defaults; override as needed.")

    # Only enable the 1-click path when we have a creator mnemonic and all addresses.
    disabled = not (ctx["creator_mn"] and (p1 and p2 and p3 and primary_seller))

    if st.button(
        "🚀 One-Click: Mint ASA → Deploy Router → Opt-ins → Prefund",
        disabled=disabled,
        use_container_width=True,
    ):
        try:
            # Identify potential funders (bank/seller/admin/buyer) for min-balance and fee top-ups.
            funders = available_funders(
                ctx["bank_mn"],
                ctx["seller_mn"],
                ctx["admin_mn"],
                ctx["buyer_mn"],
                ctx["creator_addr"],
            )

            # 1) Mint a demo Ticket ASA (decimals=0). Under the hood this routine
            #    funds the creator/account as needed to satisfy MBR/fees.
            asa_id = create_demo_ticket_asa_auto(
                c,
                creator_addr=ctx["creator_addr"],
                creator_mn=ctx["creator_mn"],
                funders=funders,
                unit=qs_unit,
                name=qs_name,
                total=int(qs_total),
                decimals=0,
            )

            # Save for downstream tabs (trade, tools, etc.)
            ss["DEPLOY_ASA_ID"] = ss["TRADE_ASA_ID"] = int(asa_id)

            # 2) Deploy the Router app configured with splits/royalty and seller.
            app_id = deploy_router_app(
                c,
                creator_addr=ctx["creator_addr"],
                creator_mn=ctx["creator_mn"],
                p1=p1,
                p2=p2,
                p3=p3,
                bps1=bps1,
                bps2=bps2,
                bps3=bps3,
                roy_bps=roy_bps,
                asa_id=int(asa_id),
                primary_seller=primary_seller,
                funders=funders,
            )

            ss["TRADE_APP_ID"] = int(app_id)

            # Keep QuickStart focused on creation; opt-ins/prefund live on Trade tab.
            st.success(f"✅ Ready: ASA #{asa_id} • Router App #{app_id}")

        except Exception as e:
            # Network/contract failures are surfaced to the operator.
            st.error(f"QuickStart failed: {e}")

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────────────
    # Advanced: explicit configuration for router deployment
    # ──────────────────────────────────────────────────────────────────────
    st.subheader("Advanced Router Settings")
    col1, col2 = st.columns(2)

    with col1:
        # Use the last minted ASA as a convenience default.
        asa_id = st.number_input(
            "Ticket ASA ID", min_value=0, step=1, value=int(ss.get("DEPLOY_ASA_ID", 0))
        )

        # Allow operators to tune splits precisely; provide stable widget keys.
        bps1 = st.number_input(
            "Split bps #1 (artist)",
            min_value=0,
            max_value=10_000,
            value=7_000,
            key="deploy_bps1",
        )
        bps2 = st.number_input(
            "Split bps #2",
            min_value=0,
            max_value=10_000,
            value=2_500,
            key="deploy_bps2",
        )
        bps3 = st.number_input(
            "Split bps #3", min_value=0, max_value=10_000, value=500, key="deploy_bps3"
        )

    with col2:
        roy_bps = st.number_input(
            "Resale artist royalty bps",
            min_value=0,
            max_value=10_000,
            value=500,
            key="deploy_roy_bps",
        )
        p1 = st.text_input(
            "Payout #1 address (artist)",
            value=(settings.ARTIST_ADDR or ctx["creator_addr"] or ""),
            key="deploy_p1",
        )
        p2 = st.text_input(
            "Payout #2 address",
            value=(settings.SELLER_ADDR_PREF or ctx["seller_addr"] or ""),
            key="deploy_p2",
        )
        p3 = st.text_input(
            "Payout #3 address",
            value=(settings.ADMIN_ADDR_PREF or ctx["admin_addr"] or ""),
            key="deploy_p3",
        )
        primary_seller = st.text_input(
            "Primary seller address",
            value=(settings.SELLER_ADDR_PREF or ctx["seller_addr"] or ""),
            key="deploy_seller",
        )

    # Lightweight sanity check: Algorand addresses are base32 and 58 chars.
    bads = [x for x in [p1, p2, p3, primary_seller] if x and len(x) != 58]
    if bads:
        st.warning("One or more payout addresses look invalid (should be 58 chars).")

    # Enable deploy when we have a creator mnemonic, valid non-empty addresses, and a non-zero ASA id.
    deploy_disabled = not (
        ctx["creator_mn"] and p1 and p2 and p3 and primary_seller and int(asa_id) > 0
    )

    if st.button("Deploy Router", disabled=deploy_disabled, use_container_width=True):
        try:
            funders = available_funders(
                ctx["bank_mn"],
                ctx["seller_mn"],
                ctx["admin_mn"],
                ctx["buyer_mn"],
                ctx["creator_addr"],
            )

            app_id = deploy_router_app(
                c,
                creator_addr=ctx["creator_addr"],
                creator_mn=ctx["creator_mn"],
                p1=p1,
                p2=p2,
                p3=p3,
                bps1=bps1,
                bps2=bps2,
                bps3=bps3,
                roy_bps=roy_bps,
                asa_id=int(asa_id),
                primary_seller=primary_seller,
                funders=funders,
            )

            # Persist for Trade/Tools tabs to auto-populate.
            ss["TRADE_APP_ID"] = int(app_id)
            ss["TRADE_ASA_ID"] = int(asa_id)

            # NOTE: If you want to display the app address, import `logic` at the
            # top of this file:
            #   from algosdk.transaction import logic
            # and then uncomment this line:
            # st.success(f"✅ Router deployed — App ID: {app_id} | Address: {logic.get_application_address(app_id)}")
            st.success(f"✅ Router deployed — App ID: {app_id}")

        except Exception as e:
            st.error(f"Deploy failed: {e}")
