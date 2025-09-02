# backend/scripts/resale_via_router.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
#
# Purpose
# -------
# Execute a **resale** transaction through the Royalty Router application:
#   New buyer pays the app → app performs inner payments (artist royalty + seller)
#   → holder transfers 1 unit of the ticket ASA to the new buyer — all atomically.
#
# This script assembles the expected 3-transaction group the contract validates:
#   [0] ApplicationCall  (sender = NEW BUYER, app args = ["resale"], accounts=[p1,p2,p3,holder])
#   [1] Payment          (NEW BUYER → App) amount = price (µAlgos)
#   [2] AssetTransfer    (HOLDER → NEW BUYER) amount = 1, index = ASA
#
# Behavior matches contracts/router.py resale() expectations.
#
# Usage
# -----
#   python backend/scripts/resale_via_router.py \
#     --app 123456 \
#     --asa 777888 \
#     --price 1200000 \
#     --holder_mnemonic  "..." \
#     --newbuyer_mnemonic "..."
#
# If flags are omitted, mnemonics are read from the environment:
#   HOLDER_MNEMONIC  (falls back to BUYER_MNEMONIC for convenience)
#   NEWBUYER_MNEMONIC
#
# Environment (.env)
# ------------------
# ALGOD_URL=https://testnet-api.algonode.cloud
# ALGOD_TOKEN=aaaaaaaa...         # typically blank for Algonode
# HOLDER_MNEMONIC="... 25 words ..."
# NEWBUYER_MNEMONIC="... 25 words ..."
#
# Notes
# -----
# - AppCall uses a flat fee sufficient to cover inner txns performed by the app.
# - We include only up to four external accounts in AppCall.accounts per TEAL limits:
#     [p1, p2, p3, holder]  (seller_global is *not* included to stay within the limit).
# - This script is for TestNet demos. Audit before production.
from __future__ import annotations

import argparse
import base64
import json
import os
from typing import Any

from algosdk import account, encoding, mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import calculate_group_id, logic, wait_for_confirmation
from algosdk.v2client import algod
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment / Client
# ---------------------------------------------------------------------------

# Load variables from a .env if present (keeps parity with other scripts)
load_dotenv()

ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
# Some public nodes ignore tokens, but the SDK wants a string; keep a dummy default.
ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)


def algod_client() -> algod.AlgodClient:
    """Construct an Algod client using environment configuration."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_globals(client: algod.AlgodClient, app_id: int) -> dict[str, Any]:
    """
    Fetch and decode the application's global state.

    Returns:
      A dict mapping decoded keys -> raw values where:
        - For bytes values (type=1), value is the **base64 string** as returned by algod.
        - For uint values (type=2), value is the integer.
    """
    info = client.application_info(app_id)
    items = info["params"].get("global-state", [])
    out: dict[str, Any] = {}
    for kv in items:
        k = base64.b64decode(kv["key"]).decode(errors="ignore")
        v = kv["value"]
        out[k] = v["bytes"] if v["type"] == 1 else v["uint"]
    return out


def b64_to_addr(b64bytes: str) -> str:
    """
    Convert base64-encoded 32-byte address into Algorand checksummed string address.
    Raises if input is malformed.
    """
    raw = base64.b64decode(b64bytes)
    return encoding.encode_address(raw)


# ---------------------------------------------------------------------------
# Main (CLI)
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute resale via Royalty Router.")
    parser.add_argument("--app", type=int, required=True, help="Router application ID")
    parser.add_argument(
        "--asa", type=int, required=True, help="Ticket ASA ID (decimals=0 expected)"
    )
    parser.add_argument(
        "--price", type=int, required=True, help="Resale price in microAlgos (µAlgos)"
    )

    # Mnemonics may be passed explicitly; otherwise read from env.
    parser.add_argument(
        "--holder_mnemonic",
        default=None,
        help="Current ticket holder mnemonic; defaults to HOLDER_MNEMONIC or BUYER_MNEMONIC",
    )
    parser.add_argument(
        "--newbuyer_mnemonic",
        default=None,
        help="New buyer mnemonic; defaults to NEWBUYER_MNEMONIC",
    )
    args = parser.parse_args()

    # Basic validation of numeric inputs
    if args.app <= 0:
        raise SystemExit("--app must be a positive integer")
    if args.asa <= 0:
        raise SystemExit("--asa must be a positive integer")
    if args.price <= 0:
        raise SystemExit("--price must be a positive integer (µAlgos)")

    # Resolve mnemonics from flags or environment, with sensible fallbacks for demos
    holder_mn = (
        args.holder_mnemonic
        or os.getenv("HOLDER_MNEMONIC")
        or os.getenv("BUYER_MNEMONIC")
    )
    newbuyer_mn = args.newbuyer_mnemonic or os.getenv("NEWBUYER_MNEMONIC")

    if not holder_mn or not newbuyer_mn:
        raise SystemExit("Set HOLDER_MNEMONIC/NEWBUYER_MNEMONIC (or pass via flags).")

    # Derive keys and addresses
    try:
        holder_sk = mnemonic.to_private_key(holder_mn)
        holder_addr = account.address_from_private_key(holder_sk)

        newbuyer_sk = mnemonic.to_private_key(newbuyer_mn)
        newbuyer_addr = account.address_from_private_key(newbuyer_sk)
    except Exception as e:
        raise SystemExit(f"Invalid mnemonic(s): {e}") from e

    client = algod_client()
    app_addr = logic.get_application_address(args.app)

    # Read global state to obtain payout addresses (p1/p2/p3)
    gs = read_globals(client, args.app)
    try:
        p1 = b64_to_addr(gs["p1"])
        p2 = b64_to_addr(gs["p2"])
        p3 = b64_to_addr(gs["p3"])
        # Do NOT include seller_global to stay within TEAL accounts limit (≤4):
        # accounts = [p1, p2, p3, holder]
        # seller_global = b64_to_addr(gs["seller"])
    except KeyError as e:
        raise SystemExit(
            f"Router global state missing key {e!s}. Verify deployment."
        ) from e

    # Suggested params with deterministic flat fees:
    # - AppCall must cover inner payments performed by the router.
    # - Payment and AssetTransfer keep flat fees for predictability in demos.
    sp0 = client.suggested_params()
    sp0.flat_fee = True
    sp0.fee = 4_000  # app-call + inner tx coverage (tune per program)

    sp1 = client.suggested_params()
    sp1.flat_fee = True
    sp1.fee = 1_000  # payment

    sp2 = client.suggested_params()
    sp2.flat_fee = True
    sp2.fee = 1_000  # asa transfer

    # [0] AppCall "resale" — IMPORTANT: AppCall at group index 0.
    # Include payout accounts + current holder in accounts[] respecting the 4-account limit.
    app_call = ftxn.ApplicationNoOpTxn(
        sender=newbuyer_addr,
        sp=sp0,
        index=args.app,
        app_args=[b"resale"],
        accounts=[p1, p2, p3, holder_addr],
    )

    # [1] Payment — new buyer pays the app the resale price
    pay = ftxn.PaymentTxn(
        sender=newbuyer_addr,
        sp=sp1,
        receiver=app_addr,
        amt=args.price,
    )

    # [2] ASA transfer — holder delivers exactly 1 unit to the new buyer
    asa_txn = ftxn.AssetTransferTxn(
        sender=holder_addr,
        sp=sp2,
        receiver=newbuyer_addr,
        amt=1,
        index=args.asa,
    )

    # Group and sign with the correct signers:
    # - New buyer signs: AppCall, Payment
    # - Holder signs: AssetTransfer
    txns = [app_call, pay, asa_txn]
    gid = calculate_group_id(txns)
    for t in txns:
        t.group = gid

    stx_app = app_call.sign(newbuyer_sk)
    stx_pay = pay.sign(newbuyer_sk)
    stx_asa = asa_txn.sign(holder_sk)

    # Submit atomically and wait for confirmation
    txid = client.send_transactions([stx_app, stx_pay, stx_asa])
    wait_for_confirmation(client, txid, 4)

    # Emit a compact, script-friendly JSON result
    print(
        json.dumps(
            {"txid": txid, "app_id": args.app, "asa": args.asa, "price": args.price},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
