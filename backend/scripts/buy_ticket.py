# backend/scripts/buy_ticket.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# High-level purpose:
# -------------------
# Execute a **primary ticket purchase** against the Royalty Router smart contract.
# The flow is an atomic group of 3 transactions:
#   1) ApplicationCall (buyer → router)    : app_args = ["buy"], accounts = [p1,p2,p3,seller]
#   2) Payment        (buyer → app addr)   : amount = price (in microAlgos)
#   3) AssetTransfer  (seller → buyer)     : amount = 1 unit of the ticket ASA
#
# The Router validates group order and uses inner transactions to split revenue
# to p1/p2/p3 according to configured basis points (bps).
#
# Safety/UX notes:
# - The AppCall must pay a **flat fee** high enough to cover inner txns; we use 4000 µAlgos.
# - Seller and buyer sign only their own transactions.
# - This script targets **Algorand TestNet** by default; configure via .env or flags.
#
# Usage:
#   python backend/scripts/buy_ticket.py --app 123 --asa 456 --price 1000000
#     [--buyer_mnemonic "..."] [--seller_mnemonic "..."]
#
# Output (JSON to stdout):
#   { "txid": "<group txid>", "app_id": 123, "asa": 456, "price": 1000000 }
#
# Dependencies:
#   - algosdk >= 2.7
#   - python-dotenv
#   - .env containing ALGOD_URL / ALGOD_TOKEN (optional), BUYER_MNEMONIC / SELLER_MNEMONIC (optional)

from __future__ import annotations

import argparse
import base64
import json
import os
from typing import Any

from algosdk import account, encoding, mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import (
    calculate_group_id,
    logic,
    wait_for_confirmation,
)
from algosdk.v2client import algod
from dotenv import load_dotenv

# ------------------------------------------------------------------------------
# Environment & client bootstrap
# ------------------------------------------------------------------------------

load_dotenv()

# Default to Algonode TestNet; ALGOD_TOKEN can be blank for Algonode.
ALGOD_URL = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
ALGOD_TOKEN = os.getenv("ALGOD_TOKEN", "a" * 64)


def algod_client() -> algod.AlgodClient:
    """Construct a stateless algod client using environment configuration."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------


def _positive_int(value: str) -> int:
    """argparse type: ensure strictly positive integer."""
    try:
        iv = int(value, 10)
    except ValueError as e:
        raise argparse.ArgumentTypeError("must be an integer") from e
    if iv <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return iv


def read_globals(client: algod.AlgodClient, app_id: int) -> dict[str, Any]:
    """
    Read **global state** of the Router app.

    Returns keys as Python types:
      - bytes (base64 as returned by algod) preserved under their TEAL keys (e.g., "p1").
      - uints as Python ints.

    Note:
    - For byte values that represent **addresses**, we keep the base64 as-is and decode later
      (so callers can decide how to treat non-address bytes).
    """
    info = client.application_info(app_id)
    params = info.get("params", {})
    kvs = params.get("global-state", [])
    out: dict[str, Any] = {}
    for kv in kvs:
        k_b64 = kv.get("key", "")
        try:
            k = base64.b64decode(k_b64).decode("utf-8")
        except Exception:
            # Skip malformed keys; leave a clear breadcrumb for debugging.
            continue
        v = kv.get("value", {})
        if v.get("type") == 1:  # bytes
            out[k] = v.get("bytes", "")
        else:  # uint (algod encodes all ints as uint)
            out[k] = int(v.get("uint", 0))
    return out


def b64_to_addr(b64bytes: str) -> str:
    """
    Convert base64-encoded 32-byte public key into an Algorand address string.

    Raises:
      ValueError if the decoded length is not exactly 32 bytes.
    """
    raw = base64.b64decode(b64bytes or "")
    if len(raw) != 32:
        raise ValueError("global-state bytes is not a 32-byte public key")
    return encoding.encode_address(raw)


# ------------------------------------------------------------------------------
# Main flow
# ------------------------------------------------------------------------------


def main() -> None:
    # CLI arguments
    ap = argparse.ArgumentParser(
        prog="buy_ticket.py",
        description="Execute a primary ticket purchase through the Royalty Router.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--app", type=_positive_int, required=True, help="Router application ID"
    )
    ap.add_argument(
        "--asa", type=_positive_int, required=True, help="Ticket ASA ID (decimals=0)"
    )
    ap.add_argument(
        "--price", type=_positive_int, required=True, help="Price in microAlgos"
    )
    ap.add_argument(
        "--buyer_mnemonic",
        default=None,
        help="Buyer 25-word mnemonic (overrides BUYER_MNEMONIC env)",
    )
    ap.add_argument(
        "--seller_mnemonic",
        default=None,
        help="Seller 25-word mnemonic (overrides SELLER_MNEMONIC env)",
    )
    args = ap.parse_args()

    # Resolve secrets from flags or environment.
    buyer_mn = args.buyer_mnemonic or os.getenv("BUYER_MNEMONIC")
    seller_mn = args.seller_mnemonic or os.getenv("SELLER_MNEMONIC")
    if not buyer_mn or not seller_mn:
        raise SystemExit(
            "Set BUYER_MNEMONIC and SELLER_MNEMONIC (or pass via --buyer_mnemonic/--seller_mnemonic)"
        )

    # Derive private keys / addresses.
    buyer_sk = mnemonic.to_private_key(buyer_mn)
    seller_sk = mnemonic.to_private_key(seller_mn)
    buyer_addr = account.address_from_private_key(buyer_sk)
    seller_addr = account.address_from_private_key(seller_sk)

    client = algod_client()
    app_addr = logic.get_application_address(args.app)

    # Fetch Router global state and decode payout addresses.
    # Required globals: "p1", "p2", "p3", "seller"
    gs = read_globals(client, args.app)
    try:
        p1 = b64_to_addr(gs["p1"])
        p2 = b64_to_addr(gs["p2"])
        p3 = b64_to_addr(gs["p3"])
        seller_global = b64_to_addr(gs["seller"])
    except KeyError as ke:
        raise SystemExit(f"Router missing global key: {ke}") from ke
    except ValueError as ve:
        raise SystemExit(f"Router global address decode failed: {ve}") from ve

    # Suggested params:
    #  - sp0 must be **flat fee** and large enough to sponsor inner payments created by the app.
    #  - sp1, sp2 are standard dynamic fees for payment and ASA transfer.
    sp0 = client.suggested_params()
    sp0.flat_fee = True
    sp0.fee = 4000  # conservative for 3 inner payments
    sp1 = client.suggested_params()
    sp2 = client.suggested_params()

    # 1) ApplicationCall: "buy"
    #    Provide payout recipients via `accounts` so the app can reference them.
    #    SDK 2.7.0 uses `index` arg for app id.
    app_call = ftxn.ApplicationNoOpTxn(
        sender=buyer_addr,
        sp=sp0,
        index=args.app,
        app_args=[b"buy"],
        accounts=[p1, p2, p3, seller_global],
    )

    # 2) Payment: buyer → app address (router contract address)
    pay = ftxn.PaymentTxn(
        sender=buyer_addr,
        sp=sp1,
        receiver=app_addr,
        amt=args.price,
    )

    # 3) AssetTransfer: seller → buyer (exactly 1 unit of ticket ASA)
    asa_transfer = ftxn.AssetTransferTxn(
        sender=seller_addr,
        sp=sp2,
        receiver=buyer_addr,
        amt=1,
        index=args.asa,
    )

    # Atomic group: [AppCall, Pay, ASA]
    txns = [app_call, pay, asa_transfer]
    gid = calculate_group_id(txns)
    for t in txns:
        t.group = gid

    # Sign with the correct parties:
    # - buyer signs: app_call + pay
    # - seller signs: asa_transfer
    stx_app = app_call.sign(buyer_sk)
    stx_pay = pay.sign(buyer_sk)
    stx_asa = asa_transfer.sign(seller_sk)

    # Submit and wait for confirmation (4 rounds ≈ ~18s on TestNet).
    try:
        txid = client.send_transactions([stx_app, stx_pay, stx_asa])
        wait_for_confirmation(client, txid, 4)
    except Exception as e:
        # Surface a readable error; many failures here stem from mis-ordered group,
        # missing opt-ins, or insufficient fees/balance.
        raise SystemExit(f"Transaction group failed to confirm: {e}") from e

    # Emit a structured, machine-readable summary for piping (e.g., to `jq`).
    print(
        json.dumps(
            {"txid": txid, "app_id": args.app, "asa": args.asa, "price": args.price},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
