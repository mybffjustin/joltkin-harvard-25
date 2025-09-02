# backend/scripts/deploy_router.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# Purpose
# -------
# Deploy the **Royalty Router** application (PyTeal) to Algorand **TestNet**.
# The Router coordinates primary `buy()` and secondary `resale()` flows and
# performs split/royalty inner-payments based on global configuration.
#
# What this script does
# ---------------------
# 1) Loads & compiles the PyTeal contract from ./contracts/router.py.
# 2) Validates CLI inputs (addresses, bps ranges/sum, ASA id).
# 3) Creates the application with global state:
#      - bytes: p1, p2, p3, seller
#      - uint : bps1, bps2, bps3, roy_bps, asa
# 4) Prints a compact JSON containing { app_id, app_address, txid }.
#
# Safety / Production notes
# -------------------------
# * Script is intended for **TestNet** demos. Audit contracts before MainNet.
# * Validates that bps are within [0..10000] and sum to 10000 for primary splits.
# * Verifies Bech32 addresses and basic ASA id bounds.
# * Uses the CREATOR_MNEMONIC from .env as the app creator and payer.
#
# Example
# -------
#   python backend/scripts/deploy_router.py \
#     --artist U7...KU4 --p2 ZK...ABC --p3 VN...XYZ \
#     --bps1 7000 --bps2 2500 --bps3 500 \
#     --roy_bps 500 \
#     --asa 12345678 \
#     --seller QN...MUSQ
#
# Environment (.env)
# ------------------
# ALGOD_URL=https://testnet-api.algonode.cloud
# ALGOD_TOKEN=
# CREATOR_MNEMONIC="... 25 words ..."

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import pathlib

from algosdk import account, encoding, mnemonic, transaction
from algosdk.transaction import (
    ApplicationCreateTxn,
    OnComplete,
    StateSchema,
    wait_for_confirmation,
)
from algosdk.v2client import algod
from dotenv import load_dotenv
from pyteal import Mode, compileTeal

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# Load defaults from project root .env (if present).
load_dotenv()
ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
# Many public nodes ignore token; keep non-empty for SDK shape compatibility.
ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def algod_client() -> algod.AlgodClient:
    """Construct and return a configured Algod client."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


def compile_program(client: algod.AlgodClient, teal_src: str) -> bytes:
    """
    Compile TEAL source via algod /v2/teal/compile.

    Args:
        client: Algod client.
        teal_src: TEAL assembly (string) produced by PyTeal compileTeal().

    Returns:
        Compiled program bytes suitable for ApplicationCreateTxn.

    Raises:
        Exception: if the compile endpoint fails.
    """
    out = client.compile(teal_src)  # returns dict with "result" (b64)
    return base64.b64decode(out["result"])


def load_pyteal_module():
    """
    Dynamically import the router PyTeal module from contracts/router.py.

    Returns:
        Python module object with callables approval() and clear().

    Raises:
        FileNotFoundError: if the contracts/router.py file is missing.
        ImportError: if import execution fails.
    """
    path = pathlib.Path(__file__).resolve().parents[1] / "contracts" / "router.py"
    if not path.exists():
        raise FileNotFoundError(f"Cannot locate PyTeal contract at: {path}")
    spec = importlib.util.spec_from_file_location("router", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None, "importlib could not load router.py"
    spec.loader.exec_module(mod)
    return mod


def _normalize_mnemonic(raw: str | None) -> str:
    """
    Normalize a user-provided mnemonic string by removing shell quotes and
    collapsing whitespace. Enforces 25-word mnemonic.

    Raises:
        SystemExit: if mnemonic is missing or not 25 words.
    """
    if not raw:
        raise SystemExit("Set CREATOR_MNEMONIC to a 25-word mnemonic in .env")
    s = raw.strip().strip('"').strip("'")
    words = s.split()
    if len(words) != 25:
        raise SystemExit(f"CREATOR_MNEMONIC must contain 25 words, got {len(words)}")
    return " ".join(words)


def _creator_from_env() -> tuple[bytes, str]:
    """
    Get creator private key and address from CREATOR_MNEMONIC.

    Returns:
        (creator_sk, creator_addr)
    """
    mn = _normalize_mnemonic(os.getenv("CREATOR_MNEMONIC"))
    sk = mnemonic.to_private_key(mn)
    addr = account.address_from_private_key(sk)
    return sk, addr


def _validate_address(addr: str, label: str) -> None:
    """Ensure the given string is a valid Algorand address."""
    try:
        encoding.decode_address(addr)  # will raise on invalid
    except Exception:
        # Suppress internal decode exception context for cleaner CLI error (B904).
        raise SystemExit(f"--{label} is not a valid Algorand address: {addr}") from None


def _validate_bps(bps1: int, bps2: int, bps3: int, roy_bps: int) -> None:
    """
    Validate that each bps is within [0..10000] and primary split sums to 10000.
    Resale royalty can be any 0..10000 independent of primary-split sum.
    """
    for name, v in [
        ("bps1", bps1),
        ("bps2", bps2),
        ("bps3", bps3),
        ("roy_bps", roy_bps),
    ]:
        if not (0 <= v <= 10_000):
            raise SystemExit(f"--{name} must be in range [0..10000], got {v}")
    if bps1 + bps2 + bps3 != 10_000:
        raise SystemExit(
            f"Primary split must sum to 10000 bps, got {bps1 + bps2 + bps3}"
        )


def _validate_asa(asa: int) -> None:
    """Basic ASA id sanity check (positive integer)."""
    if asa <= 0:
        raise SystemExit(f"--asa must be a positive integer, got {asa}")


def _u64(n: int) -> bytes:
    """Encode an int as 8-byte big-endian (TEAL uint64 argument)."""
    if n < 0 or n > (1 << 64) - 1:
        raise SystemExit(f"uint64 out of range: {n}")
    return n.to_bytes(8, "big")


def _parse_args() -> argparse.Namespace:
    """CLI argument parser for Router deployment."""
    ap = argparse.ArgumentParser(
        description="Deploy the Royalty Router PyTeal application to Algorand TestNet.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--artist", required=True, help="p1 address (artist primary recipient)"
    )
    ap.add_argument("--p2", required=True, help="p2 address (split recipient)")
    ap.add_argument("--p3", required=True, help="p3 address (split recipient)")
    ap.add_argument(
        "--bps1", type=int, required=True, help="p1 basis points (0..10000)"
    )
    ap.add_argument(
        "--bps2", type=int, required=True, help="p2 basis points (0..10000)"
    )
    ap.add_argument(
        "--bps3", type=int, required=True, help="p3 basis points (0..10000)"
    )
    ap.add_argument(
        "--roy_bps",
        type=int,
        required=True,
        help="resale artist royalty bps (0..10000)",
    )
    ap.add_argument("--asa", type=int, required=True, help="ticket ASA id")
    ap.add_argument(
        "--seller", required=True, help="primary seller address (for buy() flow)"
    )
    return ap.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Entrypoint: compile PyTeal, validate args, create the Router app."""
    args = _parse_args()

    # Validate addresses and config early for fast feedback.
    for label, addr in [
        ("artist", args.artist),
        ("p2", args.p2),
        ("p3", args.p3),
        ("seller", args.seller),
    ]:
        _validate_address(addr, label)
    _validate_bps(args.bps1, args.bps2, args.bps3, args.roy_bps)
    _validate_asa(args.asa)

    # Resolve creator keys (payer & sender).
    creator_sk, creator_addr = _creator_from_env()

    # Prepare algod client and load/compile PyTeal.
    client = algod_client()
    mod = load_pyteal_module()
    approval_teal = compileTeal(mod.approval(), Mode.Application, version=8)
    clear_teal = compileTeal(mod.clear(), Mode.Application, version=8)
    ap_prog = compile_program(client, approval_teal)
    cl_prog = compile_program(client, clear_teal)

    # Global schema = 5 uints (bps1/bps2/bps3/roy_bps/asa) + 4 byte slices (p1/p2/p3/seller).
    gschema = StateSchema(num_uints=5, num_byte_slices=4)

    # App args: bytes for addresses; uint64 for numeric params.
    app_args = [
        encoding.decode_address(args.artist),  # p1
        encoding.decode_address(args.p2),  # p2
        encoding.decode_address(args.p3),  # p3
        _u64(args.bps1),
        _u64(args.bps2),
        _u64(args.bps3),
        _u64(args.roy_bps),
        _u64(args.asa),
        encoding.decode_address(args.seller),  # primary seller
    ]

    # Build, sign, submit, and wait for confirmation.
    sp = client.suggested_params()
    txn = ApplicationCreateTxn(
        sender=creator_addr,
        sp=sp,
        on_complete=OnComplete.NoOpOC,
        approval_program=ap_prog,
        clear_program=cl_prog,
        global_schema=gschema,
        local_schema=StateSchema(0, 0),
        app_args=app_args,
    )
    stxn = txn.sign(creator_sk)
    txid = client.send_transaction(stxn)
    resp = wait_for_confirmation(client, txid, 4)

    app_id = resp["application-index"]
    app_addr = transaction.logic.get_application_address(app_id)

    # Emit machine-readable result.
    print(
        json.dumps(
            {
                "app_id": app_id,
                "app_address": app_addr,
                "txid": txid,
                "algod_url": ALGOD_URL,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
