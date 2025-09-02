# backend/scripts/create_ticket_asa.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# Purpose
# -------
# Create a simple Algorand Standard Asset (ASA) to represent tickets where
# **1 unit = 1 ticket** (i.e., non-fractional; decimals default to 0).
#
# Design
# ------
# * Targets **TestNet** by default (configurable via .env).
# * Uses the **creator** account as manager/reserve/freeze/clawback (centralized).
#   For production, you may want to:
#     - set these to a multisig or governance account,
#     - or clear manager/freeze/clawback after distribution to remove control.
#
# Safety & UX
# -----------
# * Validates mnemonic length, unit/asset name constraints (Algorand protocol):
#     - unit_name:  <= 8 chars
#     - asset_name: <= 32 chars
#     - decimals:   0..19 (this script defaults to 0)
# * Outputs a small JSON blob containing the newly created asset_id + txid.
#
# Example
# -------
#   python backend/scripts/create_ticket_asa.py \
#     --unit TIX \
#     --name "TDM Ticket" \
#     --total 1000 \
#     --decimals 0 \
#     --url "https://example.com/ticket"
#
# Requirements
# ------------
#   pip install algosdk python-dotenv
#
# Environment (.env)
# ------------------
# ALGOD_URL=https://testnet-api.algonode.cloud
# ALGOD_TOKEN=
# CREATOR_MNEMONIC="... 25 words ..."

from __future__ import annotations

import argparse
import json
import os

from algosdk import account, mnemonic, transaction
from algosdk.transaction import wait_for_confirmation
from algosdk.v2client import algod
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
# Try the project root .env first, then fall back to the scripts directory.
load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
# Algonode ignores token; other providers may require one.
ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)


def get_client() -> algod.AlgodClient:
    """Construct an Algod v2 client from environment configuration."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


def _normalize_mnemonic(raw: str | None) -> str:
    """
    Normalize a user-provided mnemonic string by removing shell quotes and
    collapsing whitespace.

    Raises:
        SystemExit: if the mnemonic is missing or not exactly 25 words.
    """
    if not raw:
        raise SystemExit("Set CREATOR_MNEMONIC to a 25-word mnemonic in .env")
    # Strip surrounding quotes a user might add in .env
    s = raw.strip().strip('"').strip("'")
    words = s.split()
    if len(words) != 25:
        raise SystemExit(f"CREATOR_MNEMONIC must contain 25 words, got {len(words)}")
    return " ".join(words)


def _validate_asa_fields(unit: str, name: str, decimals: int) -> None:
    """
    Validate ASA metadata fields according to Algorand constraints.

    Raises:
        SystemExit: If any constraint is violated.
    """
    if not unit or not name:
        raise SystemExit("--unit and --name are required")
    if len(unit) > 8:
        raise SystemExit(f"--unit must be ≤ 8 characters (got {len(unit)})")
    if len(name) > 32:
        raise SystemExit(f"--name must be ≤ 32 characters (got {len(name)})")
    if not (0 <= decimals <= 19):
        raise SystemExit(f"--decimals must be in range [0..19] (got {decimals})")


def _creator_from_env() -> tuple[str, str]:
    """
    Derive creator secret key and address from CREATOR_MNEMONIC.

    Returns:
        (creator_sk, creator_addr)

    Raises:
        SystemExit: on missing/invalid mnemonic.
    """
    creator_mn = _normalize_mnemonic(os.getenv("CREATOR_MNEMONIC"))
    creator_sk = mnemonic.to_private_key(creator_mn)
    creator_addr = account.address_from_private_key(creator_sk)
    return creator_sk, creator_addr


def _build_asa_create_txn(
    c: algod.AlgodClient,
    creator_addr: str,
    *,
    unit: str,
    name: str,
    total: int,
    decimals: int,
    url: str,
    default_frozen: bool,
) -> transaction.AssetConfigTxn:
    """
    Build an ASA create transaction where the creator retains all manager roles.

    Notes:
        * Setting manager/reserve/freeze/clawback to the creator centralizes control.
          Consider governance or clearing these fields for production deployments.
    """
    sp = c.suggested_params()
    return transaction.AssetConfigTxn(
        sender=creator_addr,
        sp=sp,
        total=total,
        default_frozen=default_frozen,
        unit_name=unit,
        asset_name=name,
        manager=creator_addr,
        reserve=creator_addr,
        freeze=creator_addr,
        clawback=creator_addr,
        url=url,
        decimals=decimals,
    )


def _parse_args() -> argparse.Namespace:
    """CLI parser for ASA creation options."""
    ap = argparse.ArgumentParser(
        description="Create a Ticket ASA (1 unit = 1 ticket) on Algorand TestNet.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--unit", required=True, help="Short unit name (≤ 8 chars), e.g., TIX"
    )
    ap.add_argument(
        "--name", required=True, help="Human-readable asset name (≤ 32 chars)"
    )
    ap.add_argument(
        "--total", type=int, default=1000, help="Total supply (whole units)"
    )
    ap.add_argument(
        "--decimals", type=int, default=0, help="Decimal places (use 0 for tickets)"
    )
    ap.add_argument(
        "--url", default="https://example.com/ticket", help="Asset URL/metadata pointer"
    )
    ap.add_argument(
        "--default-frozen",
        action="store_true",
        help="Issue as frozen by default (creator can unfreeze).",
    )
    return ap.parse_args()


def main() -> None:
    """Entrypoint: validate inputs, create ASA, and print JSON result."""
    args = _parse_args()
    _validate_asa_fields(args.unit, args.name, args.decimals)

    # Resolve creator keys from environment (mnemonic not accepted via args for safety).
    creator_sk, creator_addr = _creator_from_env()

    # Build, sign, submit, and wait for ASA creation.
    client = get_client()
    txn = _build_asa_create_txn(
        client,
        creator_addr,
        unit=args.unit,
        name=args.name,
        total=args.total,
        decimals=args.decimals,
        url=args.url,
        default_frozen=bool(args.default_frozen),
    )
    stxn = txn.sign(creator_sk)
    txid = client.send_transaction(stxn)
    resp = wait_for_confirmation(client, txid, 4)

    # The asset ID is returned under 'asset-index' on creation.
    out = {
        "asset_id": resp.get("asset-index"),
        "txid": txid,
        "creator": creator_addr,
        "unit": args.unit,
        "name": args.name,
        "total": args.total,
        "decimals": args.decimals,
        "url": args.url,
        "default_frozen": bool(args.default_frozen),
        "algod_url": ALGOD_URL,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
