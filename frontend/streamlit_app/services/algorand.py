# frontend/streamlit_app/services/algorand.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Algorand service utilities.

This module centralizes common Algorand helpers used across the Streamlit demo:
  • Address/secret conversions and safe parsing helpers
  • Balance/min-balance calculations and formatting
  • Reading on-chain global/local state (Router globals, Superfan points)
  • Funding helpers (best funder selection, top-up, retry on MBR deficits)
  • One-shot ops for creating a demo ASA and deploying the Router app
  • Trading helpers (opt-in checks, asset balance)

Design principles
-----------------
- **No side effects** beyond explicit network calls; functions are pure where possible.
- **Fail safe**: defensive parsing of Indexer/Algod responses to withstand partial data.
- **Operator ergonomics**: clear error messages and small building blocks for UI code.
- **Prod-friendliness**: docstrings, types, and careful fee/MBR accounting.

Notes
-----
This code targets **Algorand TestNet** for demos. Before production use:
  • audit contract logic and transaction assembly,
  • harden error handling and logging,
  • remove mnemonic handling from UI workflows.
"""

import base64
import pathlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from algosdk import account, encoding, mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import wait_for_confirmation
from algosdk.v2client import algod, indexer
from pyteal import Mode, compileTeal

from core.constants import (
    APP_LOCAL_MBR,
    ASSET_MBR,
)

# =============================================================================
# Address & balance utilities
# =============================================================================


def addr_from_mn(mn: str | None) -> str | None:
    """Derive an Algorand address from a 25-word mnemonic.

    Args:
        mn: 25-word mnemonic (or None/empty).

    Returns:
        The corresponding account address, or None if input is falsy or invalid.
    """
    if not mn:
        return None
    try:
        return account.address_from_private_key(mnemonic.to_private_key(mn))
    except Exception:
        # Intentionally swallow to keep UI resilient to user typos.
        return None


def decode_addr_from_b64(b64_bytes: str) -> str | None:
    """Decode a base64-encoded 32-byte public key into an Algorand address.

    Args:
        b64_bytes: Base64 string; typically TEAL global/local 'bytes' value.

    Returns:
        Encoded Algorand address or None if input is malformed/wrong length.
    """
    try:
        raw = base64.b64decode(b64_bytes)
        return encoding.encode_address(raw) if len(raw) == 32 else None
    except Exception:
        return None


def algo_balance(c: algod.AlgodClient, addr: str) -> int:
    """Return the microalgo balance for an address."""
    return int(c.account_info(addr)["amount"])


def acct_min_balance(c: algod.AlgodClient, addr: str) -> int:
    """Return the current minimum required balance (µAlgos) for an address."""
    return int(c.account_info(addr).get("min-balance", 0))


def acct_amount(c: algod.AlgodClient, addr: str) -> int:
    """Return the available amount (µAlgos) for an address."""
    return int(c.account_info(addr).get("amount", 0))


def require_for_next_ops(
    c: algod.AlgodClient,
    addr: str,
    *,
    add_assets: int = 0,
    add_app_locals: int = 0,
    fee_buffer: int = 7_000,
) -> int:
    """Compute a conservative min-balance target before performing operations.

    This is used to estimate how much funding a target account should have
    *after* allocating for upcoming asset/app-local additions, plus a fee buffer.

    Args:
        c: Algod client.
        addr: Target account.
        add_assets: Number of additional assets the account will opt-in/mint.
        add_app_locals: Number of additional app local states (opt-ins).
        fee_buffer: Extra microalgos to cushion fees and rounding.

    Returns:
        Minimum µAlgos the account should retain to avoid MBR errors.
    """
    base_min = acct_min_balance(c, addr)
    delta = ASSET_MBR * int(add_assets) + APP_LOCAL_MBR * int(add_app_locals)
    return base_min + delta + int(fee_buffer)


def fmt_algos(micro: int) -> str:
    """Format microalgos as a human-friendly ALGO string."""
    return f"{micro / 1_000_000:.6f} ALGO"


# =============================================================================
# Read on-chain state
# =============================================================================


def read_router_globals(c: algod.AlgodClient, app_id: int) -> dict[str, object]:
    """Read and decode Router global state into a dict.

    TEAL key/value pairs are decoded as:
      • 'bytes' type: best-effort decode to Algorand address if 32 bytes
      • 'uint'  type: integer

    Args:
        c: Algod client.
        app_id: Router application id.

    Returns:
        Mapping of global keys to decoded values (str/int).
    """
    info = c.application_info(app_id)
    kvs = info["params"].get("global-state", [])
    out: dict[str, object] = {}
    for kv in kvs:
        try:
            k = base64.b64decode(kv["key"]).decode()
        except Exception:
            # Skip un-decodable keys; keep the reader resilient.
            continue
        v = kv["value"]
        if v["type"] == 1:  # bytes
            addr = decode_addr_from_b64(v["bytes"])
            out[k] = addr or v["bytes"]  # Prefer decoded address, fallback raw base64
        else:  # uint
            out[k] = v["uint"]
    return out


def read_points_via_indexer(
    idx: indexer.IndexerClient | None,
    app_id: int,
    limit: int = 500,
) -> list[tuple[str, int, int]]:
    """Aggregate (address, points, tier) tuples from Indexer local state.

    Scans Indexer accounts with local state for `app_id` and extracts two
    numeric values:
      - points: any of 'points'|'pts'|'p'
      - tier:   any of 'tier'|'t'

    Args:
        idx: Optional Indexer client (None → returns empty).
        app_id: Superfan app id.
        limit: Max number of accounts to traverse.

    Returns:
        A list of (address, points, tier) sorted by points desc.
    """
    if not idx or not app_id:
        return []
    try:
        results: list[tuple[str, int, int]] = []
        next_token = None
        fetched = 0
        while fetched < limit:
            resp = idx.accounts(application_id=app_id, limit=100, next=next_token)
            accounts = resp.get("accounts", [])
            if not accounts:
                break

            for acct in accounts:
                addr = acct.get("address")
                # Find the local state for our app.
                for ls in acct.get("apps-local-state", []):
                    if ls.get("id") != app_id:
                        continue
                    pts = tier = 0
                    for kv in ls.get("key-value", []):
                        try:
                            k = base64.b64decode(kv["key"]).decode(errors="ignore")
                        except Exception:
                            continue
                        v = kv.get("value", {})
                        if v.get("type") != 2:  # we want uint
                            continue
                        if k in ("points", "pts", "p"):
                            pts = v.get("uint", 0)
                        elif k in ("tier", "t"):
                            tier = v.get("uint", 0)
                    if addr and (pts > 0 or tier > 0):
                        results.append((addr, pts, tier))
                    break  # only one local state entry per app id

            fetched += len(accounts)
            next_token = resp.get("next-token")
            if not next_token:
                break

        results.sort(key=lambda x: x[1], reverse=True)
        return results
    except Exception:
        # Keep UI tolerant to transient Indexer errors.
        return []


# =============================================================================
# Funding helpers
# =============================================================================


@dataclass
class Funder:
    """Simple carrier for a potential funding source."""

    label: str  # Human-friendly label for UI (e.g., "Bank", "Seller")
    mn: str  # 25-word mnemonic (TestNet demo only)
    addr: str  # Account address


def available_funders(
    bank_mn: str | None,
    seller_mn: str | None,
    admin_mn: str | None,
    buyer_mn: str | None,
    creator_addr: str | None,
) -> list[Funder]:
    """Collect viable funders from a set of optional mnemonics.

    Excludes any funder whose address matches `creator_addr` to avoid self-pay.

    Returns:
        Ordered list of Funder objects (Bank, Seller, Admin, Buyer).
    """
    funders: list[Funder] = []
    for label, mn in [
        ("Bank", bank_mn),
        ("Seller", seller_mn),
        ("Admin", admin_mn),
        ("Buyer", buyer_mn),
    ]:
        if not mn:
            continue
        addr = addr_from_mn(mn)
        if addr and addr != creator_addr:
            funders.append(Funder(label, mn, addr))
    return funders


def pick_best_funder(c: algod.AlgodClient, funders: list[Funder]) -> Funder | None:
    """Pick the funder with the highest balance, falling back to first on error."""
    if not funders:
        return None
    try:
        return sorted(funders, key=lambda f: acct_amount(c, f.addr), reverse=True)[0]
    except Exception:
        # If balances can't be fetched, return first candidate.
        return funders[0]


def _guard_no_self_pay(funder_addr: str, target_addr: str) -> None:
    """Raise if an attempted payment is from an account to itself."""
    if funder_addr == target_addr:
        raise RuntimeError(
            "Refusing to self-pay (funder == target). Use a separate funded wallet."
        )


def top_up(
    c: algod.AlgodClient,
    sender_mn: str,
    sender_addr: str,
    receiver_addr: str,
    microalgos: int,
) -> str:
    """Send a funding payment and wait for confirmation.

    Returns:
        The payment transaction id.
    """
    _guard_no_self_pay(sender_addr, receiver_addr)
    sp = c.suggested_params()
    tx = ftxn.PaymentTxn(
        sender=sender_addr, sp=sp, receiver=receiver_addr, amt=int(microalgos)
    )
    txid = c.send_transaction(tx.sign(mnemonic.to_private_key(sender_mn)))
    wait_for_confirmation(c, txid, 4)
    return txid


def ensure_funds(
    c: algod.AlgodClient,
    funder_mn: str,
    funder_addr: str,
    target_addr: str,
    *,
    target_min_after: int,
    cushion: int = 30_000,
) -> str | None:
    """Ensure `target_addr` has at least `target_min_after + cushion` µAlgos.

    If the account is already at/above target, returns None. Otherwise funds it.

    Returns:
        txid of the top-up payment or None if no action needed.
    """
    have = acct_amount(c, target_addr)
    need = int(target_min_after) + int(cushion)
    if have >= need:
        return None
    _guard_no_self_pay(funder_addr, target_addr)
    return top_up(c, funder_mn, funder_addr, target_addr, need - have)


# Match common Algod error strings for "balance X below min Y (Z assets)"
_DEFICIT_RE = re.compile(
    r"balance\s+(\d+)\s+below\s+min\s+(\d+).*\((\d+)\s+assets\)",
    re.IGNORECASE,
)


def parse_deficit_from_error(msg: str) -> int | None:
    """Extract microalgo deficit from an Algod error message, if available.

    Args:
        msg: Error string from an Algod HTTP 400 response.

    Returns:
        The additional µAlgos required to satisfy MBR, or None if not parsable.
    """
    m = _DEFICIT_RE.search(msg or "")
    if not m:
        return None
    bal = int(m.group(1))
    minreq = int(m.group(2))
    return max(0, minreq - bal)


def with_auto_topup_retry(
    c: algod.AlgodClient,
    *,
    target_addr: str,
    do_txn: Callable[[], str],
    funders: list[Funder],
    cushion: int = 30_000,
) -> str:
    """Execute `do_txn` and retry once with an automatic top-up if MBR is short.

    This pattern improves UX by handling common "balance below min" failures
    automatically when a funder is available.

    Args:
        c: Algod client.
        target_addr: Address that must hold the MBR for the attempted `do_txn`.
        do_txn: Callable that assembles, signs, and `send_transaction()`; returns txid.
        funders: Candidate funders able to top up `target_addr`.
        cushion: Extra µAlgos to add beyond the parsed deficit.

    Returns:
        The successful txid returned by `do_txn()`.

    Raises:
        RuntimeError: If no funder is available for a detected deficit.
        Exception: Re-raises original exceptions when deficit cannot be parsed.
    """
    try:
        return do_txn()
    except Exception as e1:
        msg = str(e1)
        deficit = parse_deficit_from_error(msg)
        if deficit is None:
            # Unknown failure; let the caller surface it.
            raise
        best = pick_best_funder(c, funders)
        if not best:
            raise RuntimeError(
                f"Insufficient funds: need +{deficit}µAlgos (no funder available). Original error: {msg}"
            ) from e1
        top_up(c, best.mn, best.addr, target_addr, int(deficit) + int(cushion))
        # Retry once after top-up.
        return do_txn()


# =============================================================================
# ASA / App Ops
# =============================================================================


def create_demo_ticket_asa_auto(
    c: algod.AlgodClient,
    *,
    creator_addr: str,
    creator_mn: str,
    funders: list[Funder],
    unit: str = "TIX",
    name: str = "TDM Demo Ticket",
    total: int = 1000,
    decimals: int = 0,
) -> int:
    """Create a demo ASA for tickets, with automatic top-up and retry.

    Args:
        c: Algod client.
        creator_addr: ASA creator address (also manager/reserve/freeze/clawback).
        creator_mn: Creator mnemonic.
        funders: Candidate funders for MBR/fee top-ups.
        unit: ASA unit name (e.g., "TIX").
        name: ASA asset name (display).
        total: Total supply.
        decimals: Number of decimal places (tickets → 0).

    Returns:
        The newly created asset id.
    """
    # Estimate post-op minimum balance (1 new ASA holding) and ensure funds.
    target_min_after = require_for_next_ops(
        c, creator_addr, add_assets=1, fee_buffer=5_000
    )
    best = pick_best_funder(c, funders)
    if best:
        ensure_funds(
            c,
            best.mn,
            best.addr,
            creator_addr,
            target_min_after=target_min_after,
            cushion=30_000,
        )

    def _do() -> str:
        sp = c.suggested_params()
        txn = ftxn.AssetConfigTxn(
            sender=creator_addr,
            sp=sp,
            total=int(total),
            default_frozen=False,
            unit_name=unit,
            asset_name=name,
            manager=creator_addr,
            reserve=creator_addr,
            freeze=creator_addr,
            clawback=creator_addr,
            url="",
            decimals=int(decimals),
        )
        return c.send_transaction(txn.sign(mnemonic.to_private_key(creator_mn)))

    txid = with_auto_topup_retry(
        c,
        target_addr=creator_addr,
        do_txn=_do,
        funders=funders,
        cushion=30_000,
    )
    resp = wait_for_confirmation(c, txid, 4)
    return int(resp["asset-index"])


def deploy_router_app(
    c: algod.AlgodClient,
    *,
    creator_addr: str,
    creator_mn: str,
    p1: str,
    p2: str,
    p3: str,
    bps1: int,
    bps2: int,
    bps3: int,
    roy_bps: int,
    asa_id: int,
    primary_seller: str,
    funders: list[Funder],
) -> int:
    """Compile and deploy the Router PyTeal app with provided parameters.

    Globals encoded in `app_args`:
      p1,p2,p3 (bytes)         → payout addresses
      bps1,bps2,bps3 (uint)    → basis points for primary split
      roy_bps (uint)           → resale artist royalty bps
      asa (uint)               → ticket ASA id
      seller (bytes)           → primary seller address

    Args:
        c: Algod client.
        creator_addr: App creator/sender.
        creator_mn: Creator mnemonic.
        p1, p2, p3: Payout addresses.
        bps1, bps2, bps3: Primary split bps (sum should equal 10000).
        roy_bps: Resale artist royalty bps.
        asa_id: Ticket ASA id (decimals=0 recommended).
        primary_seller: Address for primary sales ASA transfers.
        funders: Candidate funders for MBR/fee top-ups.

    Returns:
        Deployed application id.
    """
    # Load router.py from the repo and compile to TEAL, then to program bytes.
    p = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "router.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("router", str(p))
    m = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(m)  # type: ignore[union-attr]

    ap_teal = compileTeal(m.approval(), Mode.Application, version=8)
    cl_teal = compileTeal(m.clear(), Mode.Application, version=8)

    comp_ap = c.compile(ap_teal)
    comp_cl = c.compile(cl_teal)
    ap_prog = base64.b64decode(comp_ap["result"])
    cl_prog = base64.b64decode(comp_cl["result"])

    sp = c.suggested_params()

    app_args = [
        p1.encode(),
        p2.encode(),
        p3.encode(),
        int(bps1).to_bytes(8, "big"),
        int(bps2).to_bytes(8, "big"),
        int(bps3).to_bytes(8, "big"),
        int(roy_bps).to_bytes(8, "big"),
        int(asa_id).to_bytes(8, "big"),
        primary_seller.encode(),
    ]

    def _do() -> str:
        txn = ftxn.ApplicationCreateTxn(
            sender=creator_addr,
            sp=sp,
            on_complete=ftxn.OnComplete.NoOpOC,
            approval_program=ap_prog,
            clear_program=cl_prog,
            global_schema=ftxn.StateSchema(5, 4),
            local_schema=ftxn.StateSchema(0, 0),
            app_args=app_args,
        )
        return c.send_transaction(txn.sign(mnemonic.to_private_key(creator_mn)))

    # Ensure creator can afford app creation fees/MBR, then attempt with retry.
    target_min_after = require_for_next_ops(
        c,
        creator_addr,
        add_assets=0,
        add_app_locals=0,
        fee_buffer=8_000,
    )
    best = pick_best_funder(c, funders)
    if best:
        ensure_funds(
            c,
            best.mn,
            best.addr,
            creator_addr,
            target_min_after=target_min_after,
            cushion=40_000,
        )

    txid = with_auto_topup_retry(
        c,
        target_addr=creator_addr,
        do_txn=_do,
        funders=funders,
        cushion=40_000,
    )
    resp = wait_for_confirmation(c, txid, 4)
    return int(resp["application-index"])


# =============================================================================
# Trading helpers
# =============================================================================


def is_opted_in(c: algod.AlgodClient, addr: str, asa_id: int) -> bool:
    """Return True if `addr` has an asset holding for `asa_id`."""
    ai = c.account_info(addr)
    return any(a["asset-id"] == int(asa_id) for a in ai.get("assets", []))


def asset_balance(c: algod.AlgodClient, addr: str, asa_id: int) -> int:
    """Return the integer balance for `asa_id` held by `addr` (0 if none)."""
    ai = c.account_info(addr)
    for a in ai.get("assets", []):
        if a["asset-id"] == int(asa_id):
            return int(a.get("amount", 0))
    return 0
