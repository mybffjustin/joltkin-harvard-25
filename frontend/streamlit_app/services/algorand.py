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
  • One-shot ops for creating a demo ASA and deploying the Router & Superfan apps
  • Trading helpers (opt-in checks, asset balance)

Design principles
-----------------
- No hidden side effects; functions do only what they say.
- Fail safe; tolerate partial/variant Algod/Indexer payloads.
- Operator friendly; clear errors + conservative fee/MBR buffers.
- Production-minded; typed, documented, small building blocks.

Notes
-----
Targets **TestNet** demo use. Before production: audit contracts & flows,
tighten error handling/logging, and remove mnemonic handling from UIs.
"""

from dataclasses import dataclass
from collections.abc import Callable
import base64
import pathlib
import re
import importlib.util
from typing import Any

from algosdk import account, encoding, mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import wait_for_confirmation
from algosdk.v2client import algod, indexer
from pyteal import Mode, compileTeal

from core.constants import APP_LOCAL_MBR, ASSET_MBR

# =============================================================================
# Tunables
# =============================================================================

DEFAULT_FEE_BUFFER = 7_000
CREATE_APP_FEE_BUFFER = 8_000
TOPUP_CUSHION_SMALL = 30_000
TOPUP_CUSHION_MED = 40_000

# =============================================================================
# Address & balance utilities
# =============================================================================


def _addr32(addr: str) -> bytes:
    """Decode a bech32 (58-char) Algorand address into 32 raw bytes, with checks."""
    try:
        raw = encoding.decode_address(addr)
    except Exception as e:
        raise ValueError(f"Invalid Algorand address: {addr}") from e
    if len(raw) != 32:
        raise ValueError(f"Address did not decode to 32 bytes: {addr}")
    return raw


def addr_from_mn(mn: str | None) -> str | None:
    """Derive an Algorand address from a 25-word mnemonic (or None on bad input)."""
    if not mn:
        return None
    try:
        return account.address_from_private_key(mnemonic.to_private_key(mn))
    except Exception:
        return None


def decode_addr_from_b64(b64_bytes: str) -> str | None:
    """Decode base64-encoded 32-byte key → bech32 address; None on mismatch."""
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
    fee_buffer: int = DEFAULT_FEE_BUFFER,
) -> int:
    """Conservative min-balance target before performing operations."""
    base_min = acct_min_balance(c, addr)
    delta = ASSET_MBR * int(add_assets) + APP_LOCAL_MBR * int(add_app_locals)
    return base_min + delta + int(fee_buffer)


def fmt_algos(micro: int) -> str:
    """Format µAlgos into a human string."""
    return f"{micro / 1_000_000:.6f} ALGO"


# =============================================================================
# TEAL compile helpers
# =============================================================================


def _compile_pyteal_file(
    c: algod.AlgodClient, module_path: pathlib.Path, mod_name: str, *, version: int = 8
) -> tuple[bytes, bytes]:
    """Load a PyTeal file dynamically and return (approval_prog, clear_prog) bytes."""
    spec = importlib.util.spec_from_file_location(mod_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import module at {module_path}")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    ap_teal = compileTeal(mod.approval(), Mode.Application, version=version)
    cl_teal = compileTeal(mod.clear(), Mode.Application, version=version)

    comp_ap = c.compile(ap_teal)
    comp_cl = c.compile(cl_teal)

    return base64.b64decode(comp_ap["result"]), base64.b64decode(comp_cl["result"])


# =============================================================================
# Read on-chain state
# =============================================================================


def read_router_globals(c: algod.AlgodClient, app_id: int) -> dict[str, object]:
    """Read & decode Router globals into a friendly dict."""
    info = c.application_info(app_id)
    kvs = info["params"].get("global-state", [])
    out: dict[str, object] = {}
    for kv in kvs:
        try:
            k = base64.b64decode(kv["key"]).decode()
        except Exception:
            continue
        v = kv["value"]
        if v["type"] == 1:  # bytes
            addr = decode_addr_from_b64(v["bytes"])
            out[k] = addr or v["bytes"]  # prefer real bech32 if possible
        else:
            out[k] = v["uint"]
    return out


def validate_router_globals(globals_dict: dict[str, Any]) -> list[str]:
    """Return a list of missing/invalid router globals (empty list means OK)."""
    problems: list[str] = []
    for k in ("p1", "p2", "p3", "seller"):
        v = globals_dict.get(k)
        if not (isinstance(v, str) and len(v) == 58):
            problems.append(k)
    for k in ("bps1", "bps2", "bps3", "roybps", "asa"):
        if not isinstance(globals_dict.get(k), int):
            problems.append(k)
    return problems


def read_points_via_indexer(
    idx: indexer.IndexerClient | None,
    app_id: int,
    limit: int = 500,
) -> list[tuple[str, int, int]]:
    """Aggregate (address, points, tier) tuples from Indexer local state."""
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
                # Find local state for our app.
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
                    break  # only one local state per app id

            fetched += len(accounts)
            next_token = resp.get("next-token")
            if not next_token:
                break

        results.sort(key=lambda x: x[1], reverse=True)
        return results
    except Exception:
        # Tolerate transient indexer issues
        return []


# =============================================================================
# Funding helpers
# =============================================================================


@dataclass
class Funder:
    """Potential funding source for MBR/fees."""

    label: str
    mn: str
    addr: str


def available_funders(
    bank_mn: str | None,
    seller_mn: str | None,
    admin_mn: str | None,
    buyer_mn: str | None,
    creator_addr: str | None,
) -> list[Funder]:
    """Collect viable funders (Bank, Seller, Admin, Buyer), excluding creator."""
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
    """Pick the funder with highest balance (fallback to first on error)."""
    if not funders:
        return None
    try:
        return sorted(funders, key=lambda f: acct_amount(c, f.addr), reverse=True)[0]
    except Exception:
        return funders[0]


def _guard_no_self_pay(funder_addr: str, target_addr: str) -> None:
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
    """Send a funding payment and wait for confirmation; returns txid."""
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
    cushion: int = TOPUP_CUSHION_SMALL,
) -> str | None:
    """Ensure `target_addr` has at least `target_min_after + cushion` µAlgos."""
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
    """Extract µAlgo deficit from a typical Algod MBR error line."""
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
    cushion: int = TOPUP_CUSHION_SMALL,
) -> str:
    """Execute `do_txn` and retry once with an automatic top-up if MBR is short."""
    try:
        return do_txn()
    except Exception as e1:
        msg = str(e1)
        deficit = parse_deficit_from_error(msg)
        if deficit is None:
            # Unknown failure; surface to caller
            raise
        best = pick_best_funder(c, funders)
        if not best:
            raise RuntimeError(
                f"Insufficient funds: need +{deficit}µAlgos (no funder available). Original error: {msg}"
            ) from e1
        top_up(c, best.mn, best.addr, target_addr, int(deficit) + int(cushion))
        # Retry once
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
    """Create a whole-number Ticket ASA with safe top-ups/retry."""
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
            cushion=TOPUP_CUSHION_SMALL,
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
        cushion=TOPUP_CUSHION_SMALL,
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
    """Compile and deploy Router app. Address args are passed as 32 raw bytes."""
    router_path = (
        pathlib.Path(__file__).resolve().parents[2] / "contracts" / "router.py"
    )
    ap_prog, cl_prog = _compile_pyteal_file(c, router_path, "router", version=8)

    sp = c.suggested_params()

    app_args = [
        _addr32(p1),  # bytes: 32
        _addr32(p2),  # bytes: 32
        _addr32(p3),  # bytes: 32
        int(bps1).to_bytes(8, "big"),  # uint
        int(bps2).to_bytes(8, "big"),  # uint
        int(bps3).to_bytes(8, "big"),  # uint
        int(roy_bps).to_bytes(8, "big"),  # uint
        int(asa_id).to_bytes(8, "big"),  # uint
        _addr32(primary_seller),  # bytes: 32
    ]

    def _do() -> str:
        txn = ftxn.ApplicationCreateTxn(
            sender=creator_addr,
            sp=sp,
            on_complete=ftxn.OnComplete.NoOpOC,
            approval_program=ap_prog,
            clear_program=cl_prog,
            global_schema=ftxn.StateSchema(5, 4),  # 5 uints, 4 bytes
            local_schema=ftxn.StateSchema(0, 0),
            app_args=app_args,
        )
        return c.send_transaction(txn.sign(mnemonic.to_private_key(creator_mn)))

    target_min_after = require_for_next_ops(
        c,
        creator_addr,
        add_assets=0,
        add_app_locals=0,
        fee_buffer=CREATE_APP_FEE_BUFFER,
    )
    best = pick_best_funder(c, funders)
    if best:
        ensure_funds(
            c,
            best.mn,
            best.addr,
            creator_addr,
            target_min_after=target_min_after,
            cushion=TOPUP_CUSHION_MED,
        )

    txid = with_auto_topup_retry(
        c,
        target_addr=creator_addr,
        do_txn=_do,
        funders=funders,
        cushion=TOPUP_CUSHION_MED,
    )
    resp = wait_for_confirmation(c, txid, 4)
    return int(resp["application-index"])


def deploy_superfan_app(
    c: algod.AlgodClient,
    *,
    creator_addr: str,
    creator_mn: str,
    admin_addr: str,
    funders: list[Funder],
) -> int:
    """Compile and deploy Superfan app. First arg is admin as 32 raw bytes."""
    sf_path = (
        pathlib.Path(__file__).resolve().parents[2] / "contracts" / "superfan_pass.py"
    )
    ap_prog, cl_prog = _compile_pyteal_file(c, sf_path, "superfan_pass", version=8)

    sp = c.suggested_params()
    app_args = [_addr32(admin_addr)]  # <= critical: 32 raw bytes (not ASCII)

    def _do() -> str:
        txn = ftxn.ApplicationCreateTxn(
            sender=creator_addr,
            sp=sp,
            on_complete=ftxn.OnComplete.NoOpOC,
            approval_program=ap_prog,
            clear_program=cl_prog,
            global_schema=ftxn.StateSchema(0, 1),  # 0 uints, 1 bytes (admin)
            local_schema=ftxn.StateSchema(2, 0),  # pts, tier
            app_args=app_args,
        )
        return c.send_transaction(txn.sign(mnemonic.to_private_key(creator_mn)))

    target_min_after = require_for_next_ops(
        c, creator_addr, add_assets=0, add_app_locals=0, fee_buffer=6_000
    )
    best = pick_best_funder(c, funders)
    if best:
        ensure_funds(
            c,
            best.mn,
            best.addr,
            creator_addr,
            target_min_after=target_min_after,
            cushion=TOPUP_CUSHION_SMALL,
        )

    txid = with_auto_topup_retry(
        c,
        target_addr=creator_addr,
        do_txn=_do,
        funders=funders,
        cushion=TOPUP_CUSHION_SMALL,
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
    """Return integer balance for `asa_id` held by `addr` (0 if none)."""
    ai = c.account_info(addr)
    for a in ai.get("assets", []):
        if a["asset-id"] == int(asa_id):
            return int(a.get("amount", 0))
    return 0
