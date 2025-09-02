# frontend/streamlit_app/ui/sidebar.py
# SPDX-License-Identifier: Apache-2.0
"""Sidebar composition for the Streamlit operator console.

This module renders the left-hand sidebar used across the app. It collects
TestNet mnemonics (for demo purposes only), derives their corresponding
addresses, displays live balances, exposes a faucet link, and surfaces a few
session-scoped IDs (router app, ticket ASA, superfan app).

Security & Privacy
------------------
- **TestNet only.** Mnemonics are accepted here strictly for rapid demos and
  should never be production secrets.
- Streamlit text inputs are rendered as password fields, but the values live
  in the Streamlit process memory for the lifetime of the session.
- If you deploy this app publicly, consider adding rate limiting and avoiding
  any logging of mnemonics or raw addresses.

Behavior
--------
- When a mnemonic field is non-empty and valid, the corresponding account
  address is derived and shown with a truncated display along with its ALGO
  balance (fetched via Algod).
- If balance lookups fail, the UI falls back to a warning indicator rather
  than raising.
- A "Guided Student Mode" toggle is provided to let pages adapt their
  layout/UX (e.g., stacked vs. columnar presentation).

Returns
-------
`render_sidebar_and_status()` returns a context dictionary containing:
- `settings`: the loaded settings dataclass instance.
- `GUIDED_MODE`: bool indicating whether guided mode is enabled.
- `*_mn`: raw mnemonic strings as entered (creator/seller/buyer/admin/bank).
- `*_addr`: derived addresses (or `None` if mnemonic missing/invalid).

This context object is intended to be passed to page render functions.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from core.clients import get_algod
from core.config import settings
from core.state import ensure_defaults
from services.algorand import addr_from_mn, algo_balance, fmt_algos


def _sb_row(label: str, addr: str | None) -> None:
    """Render a single sidebar row with truncated address and live balance.

    The function is intentionally resilient: failures to fetch account info
    (e.g., network hiccups or invalid address) are surfaced as a non-fatal
    "n/a" indicator rather than interrupting the entire sidebar render.

    Args:
      label: Human-friendly label for the account (e.g., "Creator").
      addr: Algorand address (58 chars) or `None` if not available.
    """
    c = get_algod()

    # Nothing to render if the address is missing/invalid.
    if not addr:
        st.sidebar.write(f"**{label}**: —")
        return

    # Show a truncated address to avoid overwhelming the sidebar width.
    # Display live ALGO balance when available.
    try:
        bal = algo_balance(c, addr)
        st.sidebar.write(f"**{label}**  `{addr[:6]}…{addr[-4:]}`  ✅ {fmt_algos(bal)}")
    except Exception:
        # Graceful degradation: keep the UI responsive even if the node is down.
        st.sidebar.write(f"**{label}**  `{addr[:6]}…{addr[-4:]}`  ⚠️ n/a")


def render_sidebar_and_status() -> dict[str, Any]:
    """Render the entire sidebar and return a context dict for page use.

    This function is the single entry point that pages call to build the
    sidebar UI and to obtain a consolidated context object. It ensures that
    session defaults exist, collects mnemonics (from `.env` as initial
    values when available), derives corresponding addresses, and surfaces
    live balances. It also shows a quick TestNet faucet link and current
    session IDs tracked in `st.session_state`.

    Returns:
      A dictionary containing:
        - `settings`: Settings dataclass instance (global config).
        - `GUIDED_MODE`: Whether guided mode is enabled (bool).
        - `creator_mn`, `seller_mn`, `buyer_mn`, `admin_mn`, `bank_mn`: Mnemonics.
        - `creator_addr`, `seller_addr`, `buyer_addr`, `admin_addr`, `bank_addr`: Addresses.
    """
    # Ensure session keys exist before we reference them anywhere.
    ensure_defaults()

    st.sidebar.header("Accounts (TestNet only)")

    # Mnemonics are password inputs to avoid shoulder-surfing in demos.
    # Initial values are drawn from environment variables if present to reduce
    # typing during iterative testing.
    creator_mn = st.sidebar.text_input(
        "Creator mnemonic", os.getenv("CREATOR_MNEMONIC") or "", type="password"
    )
    seller_mn = st.sidebar.text_input(
        "Seller mnemonic", os.getenv("SELLER_MNEMONIC") or "", type="password"
    )
    buyer_mn = st.sidebar.text_input(
        "Buyer mnemonic", os.getenv("BUYER_MNEMONIC") or "", type="password"
    )
    admin_mn = st.sidebar.text_input(
        "Admin mnemonic", os.getenv("ADMIN_MNEMONIC") or "", type="password"
    )
    bank_mn = st.sidebar.text_input(
        "Bank mnemonic (funded)", os.getenv("BANK_MNEMONIC") or "", type="password"
    )

    # Derive addresses from mnemonics. Invalid or empty mnemonics yield None.
    creator_addr = addr_from_mn(creator_mn)
    seller_addr = addr_from_mn(seller_mn)
    buyer_addr = addr_from_mn(buyer_mn)
    admin_addr = addr_from_mn(admin_mn)
    bank_addr = addr_from_mn(bank_mn)

    # Global presentation preference that pages can consult to switch between
    # step-by-step (stacked) and compact (columns) layouts.
    GUIDED_MODE = st.sidebar.toggle("Guided Student Mode", value=True)

    # Balances & quick links section.
    st.sidebar.markdown("### Status & Faucet (TestNet)")
    _sb_row("Creator", creator_addr)
    _sb_row("Seller", seller_addr)
    _sb_row("Buyer", buyer_addr)
    _sb_row("Admin", admin_addr)
    _sb_row("Bank", bank_addr)

    st.sidebar.markdown("[TestNet Faucet](https://bank.testnet.algorand.network/)")
    st.sidebar.caption(
        "Paste address on the faucet page, then trigger any action here to refresh balances."
    )

    # Session-scoped IDs are shared across tabs. Display them for operator clarity.
    st.sidebar.markdown("---")
    ss = st.session_state
    st.sidebar.markdown(
        f"**Current Session**  \n"
        f"Router App ID: `{ss.get('TRADE_APP_ID', 0)}`  \n"
        f"Ticket ASA ID: `{ss.get('TRADE_ASA_ID', 0)}`  \n"
        f"Superfan App ID: `{ss.get('SF_APP_ID', 0)}`"
    )

    # Return a context dictionary consumed by page render functions.
    return dict(
        settings=settings,
        GUIDED_MODE=GUIDED_MODE,
        creator_mn=creator_mn,
        seller_mn=seller_mn,
        buyer_mn=buyer_mn,
        admin_mn=admin_mn,
        bank_mn=bank_mn,
        creator_addr=creator_addr,
        seller_addr=seller_addr,
        buyer_addr=buyer_addr,
        admin_addr=admin_addr,
        bank_addr=bank_addr,
    )
