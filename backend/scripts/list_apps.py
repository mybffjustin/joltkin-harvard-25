# backend/scripts/list_apps.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
#
# Purpose
# -------
# List Algorand applications created by a given address and (optionally)
# print classified details for each app, including:
#   - the inferred app "type" (RoyaltyRouter / SuperfanPass / Unknown)
#   - the application address (escrow)
#   - a human-friendly decoding of selected global state keys
#
# Why this exists
# ---------------
# During demos and debugging it's useful to quickly discover which apps were
# created by your creator/admin wallet, and to sanity-check their configuration
# without opening a block explorer. This script prints a concise, readable view
# and can also emit JSON for tooling.
#
# Usage
# -----
#   python backend/scripts/list_apps.py --details
#   python backend/scripts/list_apps.py --address <CREATOR_ADDR> --details --json
#
# Environment (.env)
# ------------------
# ALGOD_URL   = https://testnet-api.algonode.cloud
# ALGOD_TOKEN =                       # usually empty for public nodes
# CREATOR_MNEMONIC = "... 25 words ..."  # used if --address not provided

from __future__ import annotations

import argparse
import base64
import json
import os
from collections.abc import Iterable, Mapping
from typing import Any

from algosdk import account, encoding, mnemonic
from algosdk.transaction import logic as tx_logic
from algosdk.v2client import algod
from dotenv import load_dotenv

# Load environment once at import-time; mirror other repo scripts.
load_dotenv()

ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
# Some public providers ignore tokens; keep a non-empty default for SDK compat.
ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)


# -----------------------------------------------------------------------------
# Client / Environment helpers
# -----------------------------------------------------------------------------
def algod_client() -> algod.AlgodClient:
    """Instantiate an Algod client using env configuration."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


def addr_from_mn_or_env(mn_env: str | None) -> str | None:
    """
    Resolve a creator address from an environment variable holding a 25-word
    mnemonic. Returns None if mn_env is falsey (so caller can fall back).

    Raises:
        SystemExit: if the named env var is missing or malformed.
    """
    if not mn_env:
        return None
    words = os.getenv(mn_env)
    if not words:
        raise SystemExit(f"Env var {mn_env} not set")
    try:
        sk = mnemonic.to_private_key(words)
    except Exception as e:
        raise SystemExit(f"{mn_env} is not a valid 25-word mnemonic: {e}") from e
    return account.address_from_private_key(sk)


# -----------------------------------------------------------------------------
# Global state decoding / classification
# -----------------------------------------------------------------------------
def decode_gs(gs_list: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """
    Decode an Algorand application global-state array into a Python dict.

    Each entry:
      - 'key'   : base64-encoded key bytes
      - 'value' : {'type': 1|2, 'bytes'| 'uint': ...}
    Returns:
      Dict[str, Any] with keys decoded to UTF-8 and values left as raw:
        - bytes-values keep the original base64 string (we pretty-format later)
        - uint-values become Python int
    """
    out: dict[str, Any] = {}
    for kv in gs_list or []:
        k = base64.b64decode(kv["key"]).decode(errors="ignore")
        v = kv["value"]
        out[k] = v["bytes"] if v["type"] == 1 else v["uint"]
    return out


def classify(gs: Mapping[str, Any]) -> str:
    """
    Heuristically classify an app by the presence of expected global keys.
    """
    keys = set(gs.keys())
    if {"p1", "p2", "p3", "bps1", "bps2", "bps3", "roy_bps", "asa"} <= keys:
        return "RoyaltyRouter"
    if {"admin"} <= keys:
        return "SuperfanPass"
    return "Unknown"


def _format_gs_value(v: Any) -> str:
    """
    Render a single global-state value for CLI output:

    - uints → string(int)
    - bytes (base64) that decode to 32 bytes → Algorand address
    - other bytes → base64 truncated for readability
    """
    if isinstance(v, int):
        return str(v)
    # Expect a base64-encoded string for 'bytes' values
    try:
        raw = base64.b64decode(v)
        if len(raw) == 32:
            # Likely an address; pretty print as Bech32 address
            return encoding.encode_address(raw)
        # Non-address bytes: truncate the base64 for compactness
        return (v[:12] + "…") if isinstance(v, str) and len(v) > 12 else str(v)
    except Exception:
        # Not base64? Just stringify safely.
        return str(v)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    """CLI argument parsing."""
    ap = argparse.ArgumentParser(
        description="List Algorand apps created by an address."
    )
    ap.add_argument("--address", help="Creator address (overrides --mnemonic-env)")
    ap.add_argument(
        "--mnemonic-env",
        default="CREATOR_MNEMONIC",
        help="Env var holding mnemonic (default: CREATOR_MNEMONIC)",
    )
    ap.add_argument(
        "--details", action="store_true", help="Show global state + app address"
    )
    ap.add_argument("--json", action="store_true", help="Output JSON")
    return ap.parse_args()


def main() -> None:
    args = _parse_args()

    # Resolve creator address precedence: --address > mnemonic env var.
    addr = args.address or addr_from_mn_or_env(args.mnemonic_env)
    if not addr:
        raise SystemExit(
            "Provide --address or set the mnemonic env (e.g., CREATOR_MNEMONIC)."
        )

    c = algod_client()
    try:
        info = c.account_info(addr)
    except Exception as e:
        raise SystemExit(f"Failed to fetch account_info for {addr}: {e}") from e

    created = info.get("created-apps", []) or []
    rows: list[dict[str, Any]] = []

    for app in created:
        app_id = app.get("id")
        params = app.get("params", {})
        gs = decode_gs(params.get("global-state"))

        row: dict[str, Any] = {"id": app_id}
        if args.details:
            row["app_address"] = tx_logic.get_application_address(app_id)
            row["type"] = classify(gs)

            # Human-friendly formatted state for display
            pretty: dict[str, str] = {k: _format_gs_value(v) for k, v in gs.items()}
            row["global_state"] = pretty

        rows.append(row)

    rows.sort(key=lambda r: r["id"])

    # JSON mode for scripts/automation
    if args.json:
        print(json.dumps({"creator": addr, "apps": rows}, indent=2))
        return

    # Human-readable output
    print(f"Creator: {addr}")
    if not rows:
        print("No created apps found.")
        return

    for r in rows:
        line = f"- APP_ID {r['id']}"
        if args.details:
            line += f"  ({r.get('type', 'Unknown')})\n\tAddress: {r['app_address']}"
            gs = r.get("global_state", {})
            if gs:
                # Highlight the most relevant keys for quick scanning
                keys = (
                    "asa",
                    "roy_bps",
                    "bps1",
                    "bps2",
                    "bps3",
                    "p1",
                    "p2",
                    "p3",
                    "seller",
                    "admin",
                )
                highlights = [f"{k}={gs[k]}" for k in keys if k in gs]
                if highlights:
                    line += "\n\tState: " + ", ".join(highlights)
        print(line)


if __name__ == "__main__":
    main()
