# frontend/streamlit_app/pages/tools.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Streamlit page: Tools — Quick Helpers

Purpose
-------
Lightweight operator utilities that don't belong on a specific feature tab.
Currently includes:
  • "Auto top-up for next ASA create": funds a target account with just enough
    µAlgos to satisfy min-balance + a small cushion so they can create an ASA.

Design Notes
------------
- We intentionally compute the funding target from the live algod account info
  (min-balance, balance) to avoid hardcoding protocol constants that may evolve.
- Guardrails are added to avoid self-funding (bank == target) and obviously
  malformed target addresses.
- This page does not store mnemonics; Streamlit keeps values in memory for the
  session. Use **TestNet** mnemonics only.

Security
--------
- Mnemonics are handled strictly in-memory and never logged.
- Operator must paste a funded "bank" mnemonic each time they use top-up.
"""

from typing import Final

import streamlit as st
from algosdk import mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import wait_for_confirmation

from core.clients import get_algod
from services.algorand import addr_from_mn

# Small safety/cushion parameters (µAlgos). Tuned conservatively for TestNet UX.
_MBR_CUSHION: Final[int] = 100_000  # Extra over protocol-reported min balance
_FEE_CUSHION: Final[int] = 5_000  # Room for one or two tx fees
_SUCCESS_MARGIN: Final[int] = 20_000  # Final extra to avoid edge re-funding


def _validate_address(addr: str) -> bool:
    """Best-effort sanity check for an Algorand address (length + non-empty).

    Note: Full checksum validation would require `algosdk.encoding.is_valid_address`.
    We keep it lightweight here to avoid an extra dependency import on this page.
    """
    return bool(addr) and len(addr) == 58


def _compute_topup_needed(client, target_addr: str) -> int:
    """Compute additional µAlgos needed for a healthy 'can create ASA' state.

    Heuristic:
      need = min_balance (from algod) + _MBR_CUSHION + _FEE_CUSHION
      deficit = max(0, need - current_balance + _SUCCESS_MARGIN)

    Args:
        client: An initialized `algosdk.v2client.algod.AlgodClient`.
        target_addr: The account to check/fund.

    Returns:
        The recommended funding amount in µAlgos (0 if no top-up is needed).
    """
    info = client.account_info(target_addr)

    # `min-balance` is the protocol-calculated account requirement (MBR).
    need = int(info["min-balance"]) + _MBR_CUSHION + _FEE_CUSHION
    have = int(info["amount"])

    # Add a small success margin to avoid bouncing just below the threshold
    # after the next transaction.
    return max(0, need - have + _SUCCESS_MARGIN)


def render(ctx: dict) -> None:
    """Render the Tools tab."""
    st.header("Tools — Quick Helpers")

    # Lazily initialize algod client (cached via core.clients).
    c = get_algod()

    # ─────────────────────────────────────────────────────────────────────
    # Auto top-up helper
    # ─────────────────────────────────────────────────────────────────────
    st.subheader("Auto top-up for next ASA create")

    # Inputs:
    # - Bank mnemonic: must belong to a sufficiently funded account.
    # - Target address: student/participant account to top up.
    bank_mn = st.text_input("Bank mnemonic (funded)", type="password")
    target = st.text_input("Student/target address", value="")

    # Single-action button performs the top-up if needed.
    if st.button(
        "Top up just enough for next ASA",
        disabled=not (bank_mn and target),
        use_container_width=True,
    ):
        # Fail fast on obviously invalid inputs to save a network round-trip.
        if not _validate_address(target):
            st.error(
                "Target address looks invalid. Expecting a 58-character Algorand address."
            )
            return

        try:
            bank_addr = addr_from_mn(bank_mn)

            # Avoid confusing self-sends where the source and destination match.
            if bank_addr == target:
                st.error("Refusing to self-pay: bank address equals target.")
                return

            # Compute how much we need to send (if any).
            deficit = _compute_topup_needed(c, target)

            if deficit == 0:
                st.success("No top-up needed. Target account already healthy.")
                return

            # Build and send a simple payment transaction.
            sp = c.suggested_params()
            tx = ftxn.PaymentTxn(
                sender=bank_addr,
                sp=sp,
                receiver=target,
                amt=int(deficit),
            )
            signed = tx.sign(mnemonic.to_private_key(bank_mn))
            txid = c.send_transaction(signed)

            # Wait for network confirmation so the operator gets immediate feedback.
            wait_for_confirmation(c, txid, 4)
            st.success(f"Funded {deficit} µAlgos  |  txid={txid}")

        except Exception as e:
            # Surface concise, actionable error to the operator.
            st.error(f"Funding failed: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # Handy field checklists (no code logic)
    # ─────────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        """
- **Checklist**
  1) Public `FRONTEND_BASE_URL` confirmed
  2) Posters/stickers printed
  3) QRs taped up by location
  4) Wallets funded & flow tested
  5) Screen/leaderboard open

- **Hackathon Checklist**
  1) GitHub repo public + README
  2) Deck link live
  3) Demo script + fallback video
  4) `.env` keys safe & backed up
"""
    )
