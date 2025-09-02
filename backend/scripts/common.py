# backend/scripts/common.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# Purpose
# -------
# Small utility helpers used by CLI scripts.
# Currently provides a single subcommand to **prefund** an application
# (smart contract) with microAlgos so it can pay inner-transaction fees.
#
# Usage
# -----
#   python backend/scripts/common.py fund-app --appid 123 --amount 700000 \
#     --mnemonic "your 25-word mnemonic ..."
#
# Conventions
# -----------
# * Amounts are in **microAlgos** (µAlgos).
# * Targets Algorand **TestNet** by default (override via .env).
#
# Security
# --------
# * Mnemonics grant full control of funds — never commit them to VCS.
# * This script reads `CREATOR_MNEMONIC` from `.env` unless `--mnemonic`
#   is passed explicitly. Prefer passing via flag in CI.
# * Network errors and invalid mnemonics are surfaced with clear messages.

from __future__ import annotations

import argparse
import os

from algosdk import account, mnemonic, transaction
from algosdk.logic import get_application_address
from algosdk.transaction import wait_for_confirmation
from algosdk.v2client import algod
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# Load .env from project root if present, then fall back to script directory.
# (This mirrors typical repo layout where .env sits at the root.)
load_dotenv()  # try project root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))  # fallback

ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
ALGOD_TOKEN: str = os.getenv(
    "ALGOD_TOKEN", "a" * 64
)  # ignored by Algonode; present for SDK shape


def client() -> algod.AlgodClient:
    """
    Construct an Algod client using environment variables.

    Returns:
        algosdk.v2client.algod.AlgodClient: configured client instance.
    """
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


def fund_app(app_id: int, amount: int, from_mn: str) -> str:
    """
    Send a payment from a mnemonic-derived account to an application address.

    This is typically used to pre-fund a smart contract so it can perform
    inner transactions (e.g., payout splits) without relying on user fees.

    Args:
        app_id: The application (smart contract) ID to fund.
        amount: Amount to send in **microAlgos** (µAlgos). Must be > 0.
        from_mn: The 25-word mnemonic of the funding account (sender).

    Returns:
        The transaction ID (string) after successful confirmation.

    Raises:
        ValueError: If inputs are invalid (non-positive amount, invalid app_id/mnemonic).
        Exception:  If network submission or confirmation fails.
    """
    if app_id <= 0:
        raise ValueError(f"Invalid app id: {app_id}")
    if amount <= 0:
        raise ValueError(f"Amount must be > 0 (µAlgos). Got: {amount}")
    if not from_mn or len(from_mn.split()) < 24:
        raise ValueError("Invalid or missing 25-word mnemonic for sender")

    c = client()

    # Derive sender keys/addr from mnemonic (throws on malformed mnemonic).
    sender_sk = mnemonic.to_private_key(from_mn)
    sender_addr = account.address_from_private_key(sender_sk)
    # Application address derived deterministically from app id.
    app_addr = get_application_address(app_id)
    app_addr = transaction.logic.get_application_address(app_id)

    # Suggested params (fee/rounds); do not force flat fee here — regular payment.
    params = c.suggested_params()

    # Build, sign, and submit a plain payment transaction.
    txn = transaction.PaymentTxn(sender_addr, params, app_addr, amount)
    stxn = txn.sign(sender_sk)
    txid = c.send_transaction(stxn)

    # Block until confirmation or timeout; raises on failure.
    wait_for_confirmation(c, txid, 4)

    print(f"✅ Funded app {app_id} ({app_addr}) with {amount} µAlgos — txid: {txid}")
    return txid


def _parse_args() -> argparse.Namespace:
    """
    CLI parser for utility subcommands.

    Returns:
        Parsed argparse namespace.
    """
    ap = argparse.ArgumentParser(
        description="Common Algorand utilities (TestNet defaults).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    # fund-app: send µAlgos to the app address for inner-tx fees.
    fund = sub.add_parser(
        "fund-app",
        help="Fund an application (smart contract) address with µAlgos",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    fund.add_argument("--appid", type=int, required=True, help="Application ID to fund")
    fund.add_argument(
        "--amount", type=int, required=True, help="Amount in microAlgos (µAlgos)"
    )
    fund.add_argument(
        "--mnemonic",
        type=str,
        default=os.getenv("CREATOR_MNEMONIC"),
        help="25-word mnemonic for sender; defaults to CREATOR_MNEMONIC from .env",
    )
    return ap.parse_args()


def main() -> None:
    """
    Entrypoint for CLI execution.
    Dispatches to the requested subcommand with basic input validation.
    """
    args = _parse_args()

    if args.cmd == "fund-app":
        if not args.mnemonic:
            raise SystemExit(
                "Set CREATOR_MNEMONIC in .env or pass --mnemonic (25-word secret)"
            )
        try:
            fund_app(args.appid, args.amount, args.mnemonic)
        except Exception as e:
            # Surface a clear, single-line error for scripting/CI environments.
            raise SystemExit(f"fund-app failed: {e}") from e


if __name__ == "__main__":
    main()
