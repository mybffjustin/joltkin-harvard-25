# backend/scripts/deploy_superfan.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# Purpose
# -------
# Deploy the **Superfan Pass** PyTeal application to Algorand TestNet.
# The app tracks per-user local state:
#   - points (uint)
#   - tier   (uint)
# and a single global "admin" byte-slice (the admin address) used for auth.
#
# What this script does
# ---------------------
# 1) Loads and compiles ./contracts/superfan_pass.py (PyTeal → TEAL → program).
# 2) Validates the provided admin address.
# 3) Creates the application with correct schemas.
# 4) Prints a JSON receipt: { app_id, app_address, txid }.
#
# Notes
# -----
# * Intended for **TestNet** demos. Audit and harden before any production use.
# * Uses ADMIN_MNEMONIC (or CREATOR_MNEMONIC as a fallback) from .env as the
#   transaction sender / payer. The `--admin` CLI arg is the address stored in
#   global state and used for authorization checks in the app logic.
#
# Example
# -------
#   python backend/scripts/deploy_superfan.py --admin U7VGK...ZPTKU4
#
# Environment (.env)
# ------------------
# ALGOD_URL=https://testnet-api.algonode.cloud
# ALGOD_TOKEN=
# ADMIN_MNEMONIC="... 25 words ..."   # or CREATOR_MNEMONIC

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import pathlib

from algosdk import account, encoding, logic, mnemonic
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
# Load a .env that sits next to this script (scripts/.env) if present; fallback
# to process env if not found. This mirrors other scripts in the repo.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
# Some public nodes ignore tokens; keep a non-empty string for SDK compatibility.
ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def algod_client() -> algod.AlgodClient:
    """Instantiate a configured Algod client."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


def compile_program(client: algod.AlgodClient, teal_src: str) -> bytes:
    """
    Compile TEAL source via algod compile endpoint.

    algod /v2/teal/compile returns:
      {"hash":"...", "result":"<base64-encoded-bytes>"}

    Returns:
        The compiled program bytes suitable for ApplicationCreateTxn fields.
    """
    resp = client.compile(teal_src)
    return base64.b64decode(resp["result"])


def load_pyteal_module():
    """
    Dynamically import the PyTeal source module for Superfan Pass.

    Expects contracts/superfan_pass.py with callables approval() and clear().

    Raises:
        FileNotFoundError: if the file cannot be located.
        ImportError: if Python cannot import/execute the module.
    """
    path = (
        pathlib.Path(__file__).resolve().parents[1] / "contracts" / "superfan_pass.py"
    )
    if not path.exists():
        raise FileNotFoundError(f"Cannot locate PyTeal contract at: {path}")
    spec = importlib.util.spec_from_file_location("superfan", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None, "importlib could not load superfan_pass.py"
    spec.loader.exec_module(mod)
    return mod


def _normalize_mnemonic(raw: str | None, label: str) -> str:
    """
    Normalize a 25-word mnemonic by removing shell quotes and collapsing
    whitespace. Enforces exact 25 words for clarity.

    Args:
        raw: Raw mnemonic string (possibly quoted).
        label: Which variable we are normalizing (for error messages).

    Returns:
        Normalized 25-word mnemonic string.

    Raises:
        SystemExit: if missing or malformed.
    """
    if not raw:
        raise SystemExit(f"Set {label} to a 25-word mnemonic in your .env")
    s = raw.strip().strip('"').strip("'")
    words = s.split()
    if len(words) != 25:
        raise SystemExit(f"{label} must contain 25 words, got {len(words)}")
    return " ".join(words)


def _sender_from_env() -> tuple[bytes, str]:
    """
    Choose the transaction sender/payer mnemonic:
      1) ADMIN_MNEMONIC, else
      2) CREATOR_MNEMONIC.

    Returns:
        (private_key, address)
    """
    raw = os.getenv("ADMIN_MNEMONIC") or os.getenv("CREATOR_MNEMONIC")
    mn = _normalize_mnemonic(raw, "ADMIN_MNEMONIC/CREATOR_MNEMONIC")
    sk = mnemonic.to_private_key(mn)
    addr = account.address_from_private_key(sk)
    return sk, addr


def _validate_address(addr: str, label: str) -> None:
    """
    Ensure a Bech32 Algorand address is well-formed.

    Raises:
        SystemExit: if the address is invalid.
    """
    try:
        encoding.decode_address(addr)  # raises on invalid format
    except Exception:
        # Suppress original traceback context for cleaner CLI error (B904).
        raise SystemExit(f"--{label} is not a valid Algorand address: {addr}") from None


def _parse_args() -> argparse.Namespace:
    """Parse CLI args for Superfan deployment."""
    ap = argparse.ArgumentParser(
        description="Deploy the Superfan Pass application to Algorand TestNet.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--admin",
        required=True,
        help="Admin address to store in global state (authorizes add_points).",
    )
    return ap.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Compile PyTeal, validate inputs, create application, and emit JSON."""
    args = _parse_args()
    _validate_address(args.admin, "admin")

    # Sender/payer (admin mnemonic preferred; fallback to creator).
    sender_sk, sender_addr = _sender_from_env()

    # Load and compile PyTeal -> TEAL -> program bytes.
    client = algod_client()
    mod = load_pyteal_module()
    approval_teal = compileTeal(mod.approval(), Mode.Application, version=8)
    clear_teal = compileTeal(mod.clear(), Mode.Application, version=8)
    ap_prog = compile_program(client, approval_teal)
    cl_prog = compile_program(client, clear_teal)

    # Schemas:
    #   Global  : 1 byte-slice (admin), 0 uints
    #   Local   : 2 uints (points, tier), 0 byte-slices
    # (Earlier drafts used 2 global byte-slices; 1 is sufficient and cheaper.)
    gschema = StateSchema(num_uints=0, num_byte_slices=1)
    lschema = StateSchema(num_uints=2, num_byte_slices=0)

    # App arguments:
    # Store the admin address as **raw 32-byte public key** (decoded),
    # not as a 58-char base32 string. This matches how the contract compares
    # Txn.sender() against App.globalGet("admin").
    app_args = [encoding.decode_address(args.admin)]

    sp = client.suggested_params()
    txn = ApplicationCreateTxn(
        sender=sender_addr,
        sp=sp,
        on_complete=OnComplete.NoOpOC,
        approval_program=ap_prog,
        clear_program=cl_prog,
        global_schema=gschema,
        local_schema=lschema,
        app_args=app_args,
    )

    stxn = txn.sign(sender_sk)
    txid = client.send_transaction(stxn)
    resp = wait_for_confirmation(client, txid, 4)
    app_id = resp["application-index"]
    app_addr = logic.get_application_address(app_id)

    # Machine-readable output for scripts/CI.
    print(
        json.dumps({"app_id": app_id, "app_address": app_addr, "txid": txid}, indent=2)
    )


if __name__ == "__main__":
    main()
