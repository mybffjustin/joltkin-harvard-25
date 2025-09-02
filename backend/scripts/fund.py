# backend/scripts/fund.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# pip install py-algorand-sdk python-dotenv

"""Fund an Algorand TestNet account.

This utility supports two modes:
  1) Fixed-amount payment (send N microAlgos to a receiver).
  2) Auto top-up (calculate the *minimum required balance after* upcoming ops
     and fund just enough to clear it, with a small cushion).

Why this exists:
  - Algorand enforces a **Minimum Balance Requirement (MBR)** that increases
    when you create/opt-in to assets or apps. This script helps avoid
    "balance below min" errors by pre-funding accounts before those actions.

Security:
  - Pass mnemonics via environment variables or an interactive prompt in CI
    where possible. Avoid committing mnemonics to files or your shell history.
  - This script is intended for **TestNet** usage only.
"""

from __future__ import annotations

import argparse
import os

from algosdk import account, mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import wait_for_confirmation
from algosdk.v2client import algod
from dotenv import load_dotenv

# ────────────────────────────── Configuration ────────────────────────────────

# Load .env from the repo root or current working directory. This allows users
# to set ALGOD_URL / ALGOD_TOKEN without exporting environment variables.
load_dotenv()

# Default to Algonode public TestNet endpoints. For Algonode, the token can be
# any non-empty string; a 64-char dummy is conventional.
ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)

# MBR components (stable values at time of writing). Keep these centralized so
# the math is explicit. If network rules change, update them here.
ASSET_MBR_MICROS: int = 100_000  # per asset create/opt-in
APP_LOCAL_MBR_MICROS: int = 100_000  # per app local state opt-in


# ──────────────────────────────── Clients ────────────────────────────────────


def algod_client() -> algod.AlgodClient:
    """Construct a simple algod client using env-configured URL/token."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


# ───────────────────────────── Account helpers ───────────────────────────────


def acct_info(c: algod.AlgodClient, addr: str) -> dict:
    """Return the account info blob for `addr` (raises on RPC error)."""
    return c.account_info(addr)


def acct_amount(c: algod.AlgodClient, addr: str) -> int:
    """Return spendable microAlgos for `addr` (aka 'amount')."""
    return int(acct_info(c, addr).get("amount", 0))


def acct_min_balance(c: algod.AlgodClient, addr: str) -> int:
    """Return the current network-calculated minimum balance for `addr`."""
    return int(acct_info(c, addr).get("min-balance", 0))


# ───────────────────────────────── Payments ──────────────────────────────────


def send_payment(
    c: algod.AlgodClient,
    sender_mn: str,
    sender_addr: str,
    receiver_addr: str,
    microalgos: int,
) -> str:
    """Send `microalgos` from `sender_addr` to `receiver_addr`.

    Signs with `sender_mn`, submits, and waits for confirmation.

    Args:
      c: algod client.
      sender_mn: 25-word mnemonic for the sender.
      sender_addr: Address derived from `sender_mn`.
      receiver_addr: Recipient address.
      microalgos: Amount to send (µAlgos).

    Returns:
      Confirmed transaction ID.

    Raises:
      algosdk.* exceptions on RPC/validation/signing errors.
    """
    if microalgos <= 0:
        raise ValueError("microalgos must be > 0")

    if sender_addr == receiver_addr:
        raise ValueError("Refusing to self-pay (sender == receiver).")

    sp = c.suggested_params()
    txn = ftxn.PaymentTxn(
        sender=sender_addr,
        sp=sp,
        receiver=receiver_addr,
        amt=int(microalgos),
    )
    stx = txn.sign(mnemonic.to_private_key(sender_mn))
    txid = c.send_transaction(stx)
    wait_for_confirmation(c, txid, 4)
    return txid


# ───────────────────────────── Funding calculators ───────────────────────────


def require_for_next_ops(
    c: algod.AlgodClient,
    addr: str,
    *,
    add_assets: int = 0,
    add_app_locals: int = 0,
    fee_buffer: int = 5_000,
) -> int:
    """Compute a *target* min-balance after planned operations.

    The minimum balance requirement increases when the account adds resources.
    This function estimates the post-op minimum so you can pre-fund to at
    least that number (plus a small `fee_buffer`) to avoid failures.

    Args:
      c: algod client.
      addr: Account to evaluate.
      add_assets: Count of new assets to be created or opted into next.
      add_app_locals: Count of app local state opt-ins expected next.
      fee_buffer: Small extra to cover near-term fees (µAlgos).

    Returns:
      Target microAlgo balance the account should have *after* funding.
    """
    base_mbr = acct_min_balance(c, addr)
    delta = ASSET_MBR_MICROS * int(add_assets) + APP_LOCAL_MBR_MICROS * int(
        add_app_locals
    )
    return base_mbr + delta + int(fee_buffer)


def ensure_funds(
    c: algod.AlgodClient,
    funder_mn: str,
    funder_addr: str,
    target_addr: str,
    *,
    target_min_after: int,
    cushion: int = 20_000,
) -> str | None:
    """Ensure `target_addr` has at least `target_min_after + cushion`.

    If the target already satisfies the threshold, returns None.
    Otherwise, funds the exact deficit + `cushion` and returns the txid.

    Args:
      c: algod client.
      funder_mn: 25-word mnemonic of the funding account (bank).
      funder_addr: Address of the funding account.
      target_addr: Receiver to top up.
      target_min_after: Minimum balance the account should have after funding.
      cushion: Extra headroom beyond the computed minimum (µAlgos).

    Returns:
      Transaction ID if a payment was sent; otherwise None.
    """
    if funder_addr == target_addr:
        raise ValueError(
            "Refusing to self-pay (funder == target). Use a separate wallet."
        )

    have = acct_amount(c, target_addr)
    need = int(target_min_after) + int(cushion)
    deficit = need - have
    if deficit <= 0:
        return None

    return send_payment(c, funder_mn, funder_addr, target_addr, deficit)


# ─────────────────────────────────── CLI ─────────────────────────────────────


def main() -> None:
    """CLI entrypoint. Parses args and performs a fixed or auto funding op."""
    parser = argparse.ArgumentParser(
        description="Fund an Algorand TestNet account (fixed amount or auto top-up)."
    )
    parser.add_argument(
        "--from-mnemonic",
        "-m",
        required=True,
        help="25-word mnemonic of the funding (bank) wallet.",
    )
    parser.add_argument(
        "--to",
        "-t",
        required=True,
        help="Receiver address to fund.",
    )
    parser.add_argument(
        "--amount",
        "-a",
        type=int,
        default=0,
        help="Send this many µAlgos (if set, 'auto' mode is ignored).",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto top-up to clear min-balance for the next op (uses add-assets/add-app-locals/fee-buffer).",
    )
    parser.add_argument(
        "--add-assets",
        type=int,
        default=0,
        help=f"Number of new assets to create/opt-in next (each +{ASSET_MBR_MICROS:_} µAlgos to MBR).",
    )
    parser.add_argument(
        "--add-app-locals",
        type=int,
        default=0,
        help=f"Number of app local state opt-ins next (each +{APP_LOCAL_MBR_MICROS:_} µAlgos to MBR).",
    )
    parser.add_argument(
        "--fee-buffer",
        type=int,
        default=5_000,
        help="Extra µAlgos to cover immediate transaction fees.",
    )
    parser.add_argument(
        "--cushion",
        type=int,
        default=20_000,
        help="Extra µAlgos beyond the computed requirement for safety.",
    )
    args = parser.parse_args()

    # Construct client and derive the funding (bank) address from the mnemonic.
    c = algod_client()
    funder_addr = account.address_from_private_key(
        mnemonic.to_private_key(args.from_mnemonic)
    )

    # Mode 1: Fixed-amount transfer (takes precedence if --amount is non-zero)
    if args.amount and not args.auto:
        txid = send_payment(c, args.from_mnemonic, funder_addr, args.to, args.amount)
        print(f"sent fixed amount: {args.amount} µAlgos | txid={txid}")
        return

    # Mode 2: Auto top-up (default helpful path)
    target_min_after = require_for_next_ops(
        c,
        args.to,
        add_assets=args.add_assets,
        add_app_locals=args.add_app_locals,
        fee_buffer=args.fee_buffer,
    )
    txid = ensure_funds(
        c,
        args.from_mnemonic,
        funder_addr,
        args.to,
        target_min_after=target_min_after,
        cushion=args.cushion,
    )
    if txid:
        print(f"auto top-up sent | txid={txid}")
    else:
        print("no top-up needed")


if __name__ == "__main__":
    # Wrap in a basic try/except to ensure non-zero exit on unexpected errors in scripts.
    try:
        main()
    except Exception as exc:
        # Keep the message concise for CLI use; full trace can be added if desired.
        print(f"error: {exc}")
        raise
