# backend/scripts/quest_ops.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
#
# Purpose
# -------
# Small operational CLI for interacting with the Superfan (quests/loyalty) app:
#   - Opt a user wallet into the app
#   - Admin adds points to a user
#   - User claims a tier given a threshold
#
# This is deliberately minimal and TestNet-oriented. It mirrors the on-chain
# entrypoints implemented in contracts/superfan_pass.py.
#
# Usage
# -----
#   # 1) Opt a user into the app (uses BUYER_MNEMONIC as the "user")
#   python backend/scripts/quest_ops.py --app 123 --action optin
#
#   # 2) Admin awards points to the user
#   python backend/scripts/quest_ops.py --app 123 --action add_points --points 25
#
#   # 3) User claims a tier if points >= threshold
#   python backend/scripts/quest_ops.py --app 123 --action claim_tier --threshold 100
#
# Environment (.env)
# ------------------
# ALGOD_URL=https://testnet-api.algonode.cloud
# ALGOD_TOKEN=aaaaaaaa...          # often blank for public nodes
# ADMIN_MNEMONIC="... 25 words ..."  # used for add_points
# CREATOR_MNEMONIC="... 25 words ..."  # fallback admin if ADMIN_MNEMONIC unset
# BUYER_MNEMONIC="... 25 words ..."    # treated as the "user" in this script
#
# Notes
# -----
# - This script is intentionally opinionated: "user" is BUYER_MNEMONIC to
#   match demo flows; adjust if your environment differs.
# - Fees are conservative; Superfan add_points requires a flat fee to cover
#   the app call. Adjust if your approval program changes its inner ops.
#
from __future__ import annotations

import argparse
import os

from algosdk import account, mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import wait_for_confirmation
from algosdk.v2client import algod
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment / Constants
# ---------------------------------------------------------------------------

# Load .env that sits next to this script; keeps behavior consistent with other scripts
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
# Many public providers ignore the token; keep a non-empty default for SDK compat.
ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)

# App-call flat fee for admin add_points (no inner transactions in the demo),
# but we still set an explicit, predictable fee. Adjust if your app changes.
APP_CALL_FLAT_FEE: int = 1_000  # microAlgos


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def client() -> algod.AlgodClient:
    """Instantiate an Algod client using env configuration."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def do_opt_in(c: algod.AlgodClient, app_id: int, user_addr: str, user_sk: bytes) -> str:
    """
    Opt the user account into the Superfan application.

    Args:
      c: Algod client
      app_id: Target application ID
      user_addr: Wallet address to opt in
      user_sk:   Private key for signing

    Returns:
      The submitted transaction ID.
    """
    sp = c.suggested_params()
    txn = ftxn.ApplicationOptInTxn(sender=user_addr, sp=sp, index=app_id)
    txid = c.send_transaction(txn.sign(user_sk))
    wait_for_confirmation(c, txid, 4)
    return txid


def do_add_points(
    c: algod.AlgodClient,
    app_id: int,
    admin_addr: str,
    admin_sk: bytes,
    user_addr: str,
    points: int,
) -> str:
    """
    Admin adds points to a user (the user is passed in accounts[0]).

    Args:
      c: Algod client
      app_id: Superfan application ID
      admin_addr: Admin wallet address (must match app's admin)
      admin_sk:   Admin private key for signing
      user_addr:  Recipient wallet (will be passed via accounts[0])
      points:     Number of points to add (uint64)

    Returns:
      Submitted transaction ID.
    """
    # Encode arguments as TEAL expects: method name + uint64 amount.
    app_args = [b"add_points", points.to_bytes(8, "big")]

    # Use flat fee for deterministic UX; admin covers the fee.
    sp = c.suggested_params()
    sp.flat_fee = True
    sp.fee = APP_CALL_FLAT_FEE

    txn = ftxn.ApplicationNoOpTxn(
        sender=admin_addr,
        sp=sp,
        index=app_id,
        app_args=app_args,
        accounts=[
            user_addr
        ],  # contracts/superfan_pass.py reads Txn.accounts[1] or sender; we supply explicitly.
    )
    txid = c.send_transaction(txn.sign(admin_sk))
    wait_for_confirmation(c, txid, 4)
    return txid


def do_claim_tier(
    c: algod.AlgodClient,
    app_id: int,
    user_addr: str,
    user_sk: bytes,
    threshold: int,
) -> str:
    """
    User claims a tier if they have >= threshold points.

    Args:
      c: Algod client
      app_id: Superfan application ID
      user_addr: User wallet address (must have local state)
      user_sk:   User private key
      threshold: Required points to claim (uint64)

    Returns:
      Submitted transaction ID (note: success on-chain depends on points >= threshold).
    """
    app_args = [b"claim_tier", threshold.to_bytes(8, "big")]
    sp = c.suggested_params()
    txn = ftxn.ApplicationNoOpTxn(
        sender=user_addr,
        sp=sp,
        index=app_id,
        app_args=app_args,
    )
    txid = c.send_transaction(txn.sign(user_sk))
    wait_for_confirmation(c, txid, 4)
    return txid


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_identities() -> tuple[str, str, bytes, bytes]:
    """
    Resolve admin and user identities/keys from environment.

    Returns:
      (admin_addr, user_addr, admin_sk, user_sk)

    Raises:
      SystemExit: if required env vars are missing or invalid.
    """
    # Prefer ADMIN_MNEMONIC; fall back to CREATOR_MNEMONIC for convenience in demos.
    admin_mn = os.getenv("ADMIN_MNEMONIC") or os.getenv("CREATOR_MNEMONIC")
    user_mn = os.getenv("BUYER_MNEMONIC")  # treated as the "user" (demo convention)
    if not (admin_mn and user_mn):
        raise SystemExit(
            "Set ADMIN_MNEMONIC/CREATOR_MNEMONIC and BUYER_MNEMONIC in .env"
        )

    try:
        admin_sk = mnemonic.to_private_key(admin_mn)
        user_sk = mnemonic.to_private_key(user_mn)
    except Exception as e:
        raise SystemExit(f"Invalid mnemonic(s): {e}") from e

    admin_addr = account.address_from_private_key(admin_sk)
    user_addr = account.address_from_private_key(user_sk)
    return admin_addr, user_addr, admin_sk, user_sk


def main() -> None:
    # Parse CLI flags once; focus on ergonomics (sane defaults for points/threshold).
    ap = argparse.ArgumentParser(
        description="Operate on Superfan app (optin, add points, claim tier)."
    )
    ap.add_argument("--app", type=int, required=True, help="Superfan application ID")
    ap.add_argument(
        "--action", choices=["optin", "add_points", "claim_tier"], required=True
    )
    ap.add_argument(
        "--points", type=int, default=10, help="Points to add (admin action)"
    )
    ap.add_argument(
        "--threshold", type=int, default=100, help="Tier threshold for claim"
    )
    args = ap.parse_args()

    # Basic input validation up front.
    if args.app <= 0:
        raise SystemExit("--app must be a positive integer")

    c = client()
    admin_addr, user_addr, admin_sk, user_sk = _resolve_identities()

    try:
        if args.action == "optin":
            txid = do_opt_in(c, args.app, user_addr, user_sk)
            print(f"Opted in — txid: {txid}")
            return

        if args.action == "add_points":
            txid = do_add_points(
                c, args.app, admin_addr, admin_sk, user_addr, args.points
            )
            print(f"Added points ({args.points}) — txid: {txid}")
            return

        # args.action == "claim_tier"
        txid = do_claim_tier(c, args.app, user_addr, user_sk, args.threshold)
        print(f"Claimed tier (threshold {args.threshold}) — txid: {txid}")

    except Exception as e:
        # Surface a concise, user-actionable error; keep full trace for debugging if needed.
        # Common causes: not opted-in, wrong admin, insufficient balance/fees, bad app id.
        raise SystemExit(f"Operation failed: {e}") from e


if __name__ == "__main__":
    main()
