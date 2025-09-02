# backend/scripts/check_state.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# Purpose
# -------
# Preflight diagnostics for **primary buy** and **resale** flows that use the
# Royalty Router smart contract. This script checks:
#   • Minimum-balance requirements (MBR) for all relevant accounts
#   • ASA opt-in status and current holdings for seller/holder/buyer
#   • Expected fee budgets for the atomic group
#   • Router global-state sanity and addresses
#   • App pre-funding (so inner payments can be executed when AppCall is index 0)
#
# Output is **human-readable** with ✅/⚠️/❌ markers to guide next steps.
# No transactions are submitted; this is safe to run repeatedly.
#
# Requirements
# ------------
# - Python 3.9+
# - algosdk >= 2.7.0 (no `future` module)
# - python-dotenv for .env loading
#
# Environment (.env)
# ------------------
# ALGOD_URL, ALGOD_TOKEN (Algonode-compatible)
# CREATOR_MNEMONIC, SELLER_MNEMONIC, BUYER_MNEMONIC, ADMIN_MNEMONIC
# HOLDER_MNEMONIC, NEWBUYER_MNEMONIC (used for resale checks)
#
# Usage
# -----
#   python backend/scripts/check_state.py --mode buy    --app <APP_ID> --asa <ASA_ID> --price 1000000
#   python backend/scripts/check_state.py --mode resale --app <APP_ID> --asa <ASA_ID> --price 1200000

from __future__ import annotations

import argparse
import base64
import math
import os
import sys

from algosdk import account, encoding, mnemonic
from algosdk.v2client import algod
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

# Default to Algonode TestNet; token can be blank for Algonode.
ALGOD_URL = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
ALGOD_TOKEN = os.getenv("ALGOD_TOKEN", "a" * 64)

# Algorand Minimum Balance Requirements (MBR), in microAlgos.
# Reference: base MBR is 0.1 ALGO; +0.1 ALGO for each ASA holding.
MBR_BASE = 100_000
MBR_PER_ASA = 100_000

# Outer-transaction fee assumptions (µAlgos). Keep consistent with your client.
FEE_APP = 4_000  # AppCall at index 0, sponsoring inner payments
FEE_PAY = 1_000  # Payment (buyer/newbuyer → app)
FEE_ASA = 1_000  # AssetTransfer (seller/holder → buyer/newbuyer)

# ---------------------------------------------------------------------------
# Client & on-chain helpers
# ---------------------------------------------------------------------------


def algod_client() -> algod.AlgodClient:
    """Create a stateless algod client using environment configuration."""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)


def read_globals(client: algod.AlgodClient, app_id: int) -> dict:
    """
    Fetch router global state and return as a Python dict of TEAL keys → value.

    Bytes values are returned as **base64 strings** (as provided by algod),
    uint values as Python ints.
    """
    info = client.application_info(app_id)
    items = info["params"]["global-state"]
    out: dict[str, object] = {}
    for kv in items:
        k = base64.b64decode(kv["key"]).decode()
        v = kv["value"]
        out[k] = v["bytes"] if v["type"] == 1 else v["uint"]
    return out


def b64_to_addr(b64bytes: str) -> str:
    """
    Decode a base64-encoded 32-byte public key from TEAL global state into
    a checksum-encoded Algorand address string.
    """
    raw = base64.b64decode(b64bytes)
    return encoding.encode_address(raw)


def addr_from_env(name: str) -> str:
    """
    Resolve an address from an environment variable holding a 25-word mnemonic.
    Returns empty string on failure to avoid raising during discovery.
    """
    mn = os.getenv(name)
    if not mn:
        return ""
    try:
        sk = mnemonic.to_private_key(mn)
        return account.address_from_private_key(sk)
    except Exception:
        return ""


def get_balance(c: algod.AlgodClient, addr: str) -> int:
    """Return account balance in microAlgos."""
    return c.account_info(addr)["amount"]


def has_asa(c: algod.AlgodClient, addr: str, asa_id: int) -> tuple[bool, int]:
    """
    Check if `addr` is opted-in to `asa_id` and return (opted_in, amount).
    Opt-in exists when the asset appears in `account_info.assets`.
    """
    for a in c.account_info(addr).get("assets", []):
        if a["asset-id"] == asa_id:
            return True, a.get("amount", 0)
    return False, 0


def fmt_algo(u: int) -> str:
    """Human-friendly ALGO string with 6 decimals."""
    return f"{u / 1_000_000:.6f} ALGO"


def required_mbr(num_asas: int) -> int:
    """Compute required MBR for an account holding `num_asas` assets."""
    return MBR_BASE + num_asas * MBR_PER_ASA


def pct_of(bps: int, price: int) -> int:
    """
    Convert basis points to an amount (ceil) to be conservative.
    Avoids false negatives when comparing against balances.
    """
    return math.ceil(price * bps / 10_000)


def max_payout(price: int, bps1: int, bps2: int, bps3: int) -> int:
    """Maximum single payout amount among the three split legs."""
    return max(pct_of(bps1, price), pct_of(bps2, price), pct_of(bps3, price))


# ---------------------------------------------------------------------------
# Pretty printers
# ---------------------------------------------------------------------------


def print_header(title: str) -> None:
    """Render a section header with an underline."""
    print("\n" + "=" * len(title))
    print(title)
    print("=" * len(title))


def fail(msg: str) -> None:
    """Mark a failing condition."""
    print(f"❌ {msg}")


def ok(msg: str) -> None:
    """Mark a passing condition."""
    print(f"✅ {msg}")


def warn(msg: str) -> None:
    """Mark a non-fatal warning that may still require action."""
    print(f"⚠️  {msg}")


# ---------------------------------------------------------------------------
# Validation routines
# ---------------------------------------------------------------------------


def check_mbr_ok(
    c: algod.AlgodClient, addr: str, num_asas: int = 0, label: str = ""
) -> bool:
    """
    Verify that `addr` meets MBR for `num_asas` holdings.

    Returns:
      True if balance >= required MBR, otherwise False (and prints guidance).
    """
    bal = get_balance(c, addr)
    need = required_mbr(num_asas)
    if bal < need:
        fail(
            f"{label or addr} below MBR: {fmt_algo(bal)} < required {fmt_algo(need)} (ASAs={num_asas})"
        )
        print(f"   → Top up at least {fmt_algo(need - bal)}")
        return False
    ok(f"{label or addr} meets MBR: {fmt_algo(bal)} ≥ {fmt_algo(need)}")
    return True


def derive_addrs_from_env() -> dict[str, str]:
    """
    Resolve commonly-used addresses from mnemonics stored in environment.
    Optional values resolve to "" so the caller can decide what's required.
    """
    return {
        "CREATOR": addr_from_env("CREATOR_MNEMONIC"),
        "SELLER": addr_from_env("SELLER_MNEMONIC"),
        "BUYER": addr_from_env("BUYER_MNEMONIC"),
        "ADMIN": addr_from_env("ADMIN_MNEMONIC"),
        "HOLDER": addr_from_env("HOLDER_MNEMONIC") or addr_from_env("BUYER_MNEMONIC"),
        "NEWBUYER": addr_from_env("NEWBUYER_MNEMONIC"),
    }


def check_buy(c: algod.AlgodClient, app_id: int, asa_id: int, price: int) -> None:
    """
    Validate preconditions for the **primary buy** flow:
      - BUYER balance and ASA opt-in
      - SELLER opt-in and has >=1 unit to sell
      - Recipient accounts (p1/p2/p3) have sufficient MBR (to receive inner payments)
      - Router app pre-funded (AppCall is first, inner txns need ALGO available)
    """
    print_header("Primary BUY preflight")

    addrs = derive_addrs_from_env()
    missing = [k for k in ["BUYER", "SELLER"] if not addrs.get(k)]
    if missing:
        fail(
            f"Missing mnemonics for: {', '.join(missing)} (set in .env or pass via flags in buy script)"
        )
        return

    gs = read_globals(c, app_id)

    # Decode payout addresses from global state. Fail fast on missing keys.
    try:
        p1 = b64_to_addr(gs["p1"])
        p2 = b64_to_addr(gs["p2"])
        p3 = b64_to_addr(gs["p3"])
        _seller_global = b64_to_addr(
            gs["seller"]
        )  # decoded for presence; intentionally unused
    except KeyError as e:
        fail(f"Global state missing key {e}; ensure app deployed with p1/p2/p3/seller")
        return

    # Extract split config (default fallbacks are informational only)
    bps1 = int(gs.get("bps1", 7000))
    bps2 = int(gs.get("bps2", 2500))
    bps3 = int(gs.get("bps3", 500))
    # Removed unused roy_bps (royalty) variable; not needed in primary split.

    # Compute the app address (router's escrow address).
    from algosdk.transaction import logic

    app_addr = logic.get_application_address(app_id)

    print(f"App: {app_id}  address: {app_addr}")
    print(f"ASA: {asa_id}")
    print(f"Split bps: p1={bps1} p2={bps2} p3={bps3}  (sum={bps1 + bps2 + bps3})")

    # Check recipient MBR so inner payments don't fail.
    ok("Checking recipient accounts (p1/p2/p3) MBR …")
    m1 = check_mbr_ok(c, p1, 0, "p1")
    m2 = check_mbr_ok(c, p2, 0, "p2")
    m3 = check_mbr_ok(c, p3, 0, "p3")
    all_ok = m1 and m2 and m3

    # SELLER must be opted-in and hold ≥1 unit to transfer to BUYER.
    opt, bal = has_asa(c, addrs["SELLER"], asa_id)
    if not opt:
        fail(f"SELLER not opted-in to ASA {asa_id}")
        all_ok = False
    else:
        ok(f"SELLER opted-in to ASA {asa_id}")
    if bal < 1:
        fail(f"SELLER does not hold a ticket (has {bal})")
        all_ok = False
    else:
        ok(f"SELLER holds {bal} ticket(s)")

    # BUYER must be opted-in to receive the ASA.
    opt_b, _ = has_asa(c, addrs["BUYER"], asa_id)
    if not opt_b:
        fail(f"BUYER not opted-in to ASA {asa_id}")
        all_ok = False
    else:
        ok(f"BUYER is opted-in to ASA {asa_id}")

    # BUYER balance must cover price + outer fees + leave MBR (with 1 ASA).
    buyer_bal = get_balance(c, addrs["BUYER"])
    buyer_required = price + (FEE_APP + FEE_PAY) + required_mbr(1)
    if buyer_bal < buyer_required:
        fail(
            f"BUYER balance {fmt_algo(buyer_bal)} insufficient. Need ≥ {fmt_algo(buyer_required)} "
            f"(price {fmt_algo(price)} + fees {fmt_algo(FEE_APP + FEE_PAY)} + MBR {fmt_algo(required_mbr(1))})"
        )
        print(f"   → Top up at least {fmt_algo(buyer_required - buyer_bal)}")
        all_ok = False
    else:
        ok(f"BUYER has enough: {fmt_algo(buyer_bal)}")

    # App pre-fund requirement: AppCall is first, inner payments execute before the
    # app receives the outer Payment. Ensure at least the **largest** single split amount is available.
    need_prefund = max_payout(price, bps1, bps2, bps3)
    app_bal = get_balance(c, app_addr)
    if app_bal < need_prefund:
        fail(
            f"App pre-fund too low: {fmt_algo(app_bal)} < needed {fmt_algo(need_prefund)} "
            f"(max single payout @ {max(bps1, bps2, bps3)} bps)"
        )
        print(f"   → Fund app by at least {fmt_algo(need_prefund - app_bal)}")
        all_ok = False
    else:
        ok(f"App pre-fund OK: {fmt_algo(app_bal)} ≥ {fmt_algo(need_prefund)}")

    # Summary + guidance
    print_header("Result")
    if all_ok:
        ok("Primary BUY preconditions satisfied.")
        print(
            "Group order expected by contract: [AppCall(buy), Payment(buyer→app), AssetTransfer(seller→buyer)]"
        )
        print("Fees assumption: app=4000, pay=1000, asa=1000")
    else:
        fail("Primary BUY has issues (see above). Fix and re-run.")


def check_resale(c: algod.AlgodClient, app_id: int, asa_id: int, price: int) -> None:
    """
    Validate preconditions for the **resale** flow:
      - HOLDER owns a ticket and is opted-in
      - NEWBUYER is opted-in and funded for price + fees + MBR
      - Recipient accounts (p1/p2/p3) have sufficient MBR
      - App pre-funding adequate for inner royalty/seller payments
    """
    print_header("Resale preflight")

    addrs = derive_addrs_from_env()
    missing = [k for k in ["HOLDER", "NEWBUYER"] if not addrs.get(k)]
    if missing:
        fail(
            f"Missing mnemonics for: {', '.join(missing)} (set HOLDER_MNEMONIC/NEWBUYER_MNEMONIC)"
        )
        return

    gs = read_globals(c, app_id)
    try:
        p1 = b64_to_addr(gs["p1"])
        p2 = b64_to_addr(gs["p2"])
        p3 = b64_to_addr(gs["p3"])
        _seller_global = b64_to_addr(
            gs["seller"]
        )  # decoded for presence; intentionally unused
    except KeyError as e:
        fail(f"Global state missing key {e}; ensure app deployed with p1/p2/p3/seller")
        return

    bps1 = int(gs.get("bps1", 7000))
    bps2 = int(gs.get("bps2", 2500))
    bps3 = int(gs.get("bps3", 500))

    from algosdk.transaction import logic

    app_addr = logic.get_application_address(app_id)

    print(f"App: {app_id}  address: {app_addr}")
    print(f"ASA: {asa_id}")
    print(f"Split bps: p1={bps1} p2={bps2} p3={bps3}  (sum={bps1 + bps2 + bps3})")

    # Check payout recipients' MBR first.
    ok("Checking recipient accounts (p1/p2/p3) MBR …")
    all_ok = True
    all_ok &= check_mbr_ok(c, p1, 0, "p1")
    all_ok &= check_mbr_ok(c, p2, 0, "p2")
    all_ok &= check_mbr_ok(c, p3, 0, "p3")

    # HOLDER must be opted-in and own ≥1 ticket.
    opt_h, bal_h = has_asa(c, addrs["HOLDER"], asa_id)
    if not opt_h:
        fail(f"HOLDER not opted-in to ASA {asa_id}")
        all_ok = False
    elif bal_h < 1:
        fail("HOLDER has 0 tickets to sell")
        all_ok = False
    else:
        ok(f"HOLDER owns {bal_h} ticket(s)")

    # NEWBUYER must be opted-in to receive.
    opt_nb, _ = has_asa(c, addrs["NEWBUYER"], asa_id)
    if not opt_nb:
        fail(f"NEWBUYER not opted-in to ASA {asa_id}")
        all_ok = False
    else:
        ok("NEWBUYER is opted-in")

    # NEWBUYER must cover price + outer fees + MBR (post-receipt: 1 ASA).
    nb_bal = get_balance(c, addrs["NEWBUYER"])
    nb_required = price + (FEE_APP + FEE_PAY) + required_mbr(1)
    if nb_bal < nb_required:
        fail(
            f"NEWBUYER balance {fmt_algo(nb_bal)} insufficient. Need ≥ {fmt_algo(nb_required)} "
            f"(price {fmt_algo(price)} + fees {fmt_algo(FEE_APP + FEE_PAY)} + MBR {fmt_algo(required_mbr(1))})"
        )
        print(f"   → Top up at least {fmt_algo(nb_required - nb_bal)}")
        all_ok = False
    else:
        ok(f"NEWBUYER has enough: {fmt_algo(nb_bal)}")

    # HOLDER should have at least the ASA transfer fee (and keep their own MBR).
    holder_bal = get_balance(c, addrs["HOLDER"])
    if holder_bal < FEE_ASA + required_mbr(1):  # conservative guidance
        warn(
            f"HOLDER low balance ({fmt_algo(holder_bal)}). Needs ≥ {fmt_algo(FEE_ASA)} for fee (plus own MBR)."
        )

    # App pre-funding: inner royalty to p1 and remainder to HOLDER.
    need_prefund = max_payout(price, bps1, bps2, bps3)
    app_bal = get_balance(c, app_addr)
    if app_bal < need_prefund:
        fail(
            f"App pre-fund too low: {fmt_algo(app_bal)} < needed {fmt_algo(need_prefund)} (max single payout)"
        )
        print(f"   → Fund app by at least {fmt_algo(need_prefund - app_bal)}")
        all_ok = False
    else:
        ok(f"App pre-fund OK: {fmt_algo(app_bal)} ≥ {fmt_algo(need_prefund)}")

    # Friendly reminder about accounts[] and group order.
    print(
        "\nHint: Ensure resale AppCall includes accounts=[p1,p2,p3,seller,holder] and AppCall is group index 0."
    )

    print_header("Result")
    if all_ok:
        ok("Resale preconditions satisfied.")
        print(
            "Group order expected by contract: [AppCall(resale), Payment(newbuyer→app), AssetTransfer(holder→newbuyer)]"
        )
        print("Fees assumption: app=4000, pay=1000, asa=1000")
    else:
        fail("Resale has issues (see above). Fix and re-run.")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments, ping algod, and run the selected preflight."""
    ap = argparse.ArgumentParser(
        description="Check preconditions for buy/resale on Router app",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--mode",
        choices=["buy", "resale"],
        required=True,
        help="Which flow to validate",
    )
    ap.add_argument("--app", type=int, required=True, help="Router app id")
    ap.add_argument("--asa", type=int, required=True, help="Ticket ASA id")
    ap.add_argument("--price", type=int, required=True, help="Price in microAlgos")
    args = ap.parse_args()

    c = algod_client()

    # Quick connectivity check; fail fast with actionable error.
    try:
        c.status()
    except Exception as e:
        fail(f"Cannot reach algod at {ALGOD_URL}: {e}")
        sys.exit(1)

    if args.mode == "buy":
        check_buy(c, args.app, args.asa, args.price)
    else:
        check_resale(c, args.app, args.asa, args.price)


if __name__ == "__main__":
    main()
