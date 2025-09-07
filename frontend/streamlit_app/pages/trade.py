# frontend/streamlit_app/pages/trade.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Buy / Resale (auto 1-click demo)

Primary Buy (1-click) now auto-prepares:
• Router prefund for inner txns
• Seller: opt-in + fund + receives 1 ticket from Creator
• Buyer: opt-in + fund
Then executes [Payment, AppCall("buy"), Axfer] per Router contract.

Resale (1-click demo) auto-prepares:
• Holder (previous Buyer) and New Buyer (Admin, else Seller)
• Router prefund, opt-ins, funding
Then executes [Payment, AppCall("resale"), Axfer].
"""

# --- stable imports path for local packages ----------------------------------
import pathlib
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
# -----------------------------------------------------------------------------

import streamlit as st
from algosdk import mnemonic
from algosdk import transaction as ftxn
from algosdk.transaction import logic, wait_for_confirmation

from core.clients import get_algod
from core.constants import APP_CALL_INNER_FEE, MIN_BALANCE
from services.algorand import (
    addr_from_mn,
    algo_balance,
    asset_balance,
    is_opted_in,
    read_router_globals,
    available_funders,
    pick_best_funder,
)
from ui.keys import k

# ============================== Helpers ======================================


def _load_last_router_id(c, creator_addr: str | None) -> int | None:
    if not creator_addr:
        return None
    try:
        info = c.account_info(creator_addr)
        apps = sorted(info.get("created-apps", []), key=lambda a: a["id"])
        for app in reversed(apps):
            keys = set()
            for kv in app.get("params", {}).get("global-state", []):
                import base64

                try:
                    keys.add(base64.b64decode(kv["key"]).decode())
                except Exception:
                    pass
            if {"p1", "p2", "p3", "bps1", "bps2", "bps3"}.issubset(keys):
                return int(app["id"])
    except Exception:
        pass
    return None


def _router_and_asa_inputs(ss) -> tuple[int, int, int]:
    app_id = st.number_input(
        "Router App ID",
        min_value=0,
        step=1,
        value=int(ss.get("TRADE_APP_ID", 0)),
        key=k("trade", "router_app_id"),
    )
    asa_id = st.number_input(
        "Ticket ASA ID",
        min_value=0,
        step=1,
        value=int(ss.get("TRADE_ASA_ID", 0)),
        key=k("trade", "ticket_asa_id"),
    )
    price = st.number_input(
        "Price (µAlgos)",
        min_value=0,
        step=1_000,
        value=int(ss.get("TRADE_PRICE", 1_000_000)),
        key=k("trade", "price_microalgos"),
        help="Total µAlgos the buyer/new buyer pays to the Router application.",
    )
    ss["TRADE_APP_ID"], ss["TRADE_ASA_ID"], ss["TRADE_PRICE"] = (
        int(app_id),
        int(asa_id),
        int(price),
    )
    return int(app_id), int(asa_id), int(price)


def _guard_router_globals_valid(globals_: dict, needs_seller: bool = True) -> None:
    req = ["p1", "p2", "p3"] + (["seller"] if needs_seller else [])
    addrs = [globals_.get(x) for x in req]
    if not all(isinstance(a, str) and len(a) == 58 for a in addrs):
        missing = [
            r
            for r, a in zip(req, addrs, strict=False)
            if not (isinstance(a, str) and len(a) == 58)
        ]
        raise RuntimeError(f"Router globals missing/invalid: {', '.join(missing)}.")


def _amount_or_zero(c, addr: str) -> int:
    try:
        return int(c.account_info(addr).get("amount", 0))
    except Exception:
        return 0


def _best_funder_excluding(c, ctx: dict, *exclude_addrs: str):
    raw = available_funders(
        ctx.get("bank_mn"),
        ctx.get("seller_mn"),
        ctx.get("admin_mn"),
        ctx.get("buyer_mn"),
        ctx.get("creator_addr"),
    )
    cand = [f for f in raw if f.addr not in set(a for a in exclude_addrs if a)]
    return pick_best_funder(c, cand)


def _top_up_account(c, ctx: dict, target_addr: str, *, min_target: int) -> str | None:
    """Fund `target_addr` up to min_target using the best non-self funder."""
    have = _amount_or_zero(c, target_addr)
    need = max(0, int(min_target) - have)
    if need == 0:
        return None
    best = _best_funder_excluding(c, ctx, target_addr)
    if not best:
        raise RuntimeError(
            f"Need ~{min_target/1e6:.3f} ALGO for {target_addr}, but no external funder is configured."
        )
    sp = c.suggested_params()
    pay = ftxn.PaymentTxn(sender=best.addr, sp=sp, receiver=target_addr, amt=need)
    txid = c.send_transaction(pay.sign(mnemonic.to_private_key(best.mn)))
    wait_for_confirmation(c, txid, 4)
    return txid


def _ensure_opt_in(c, mn: str, addr: str, asa_id: int) -> None:
    if is_opted_in(c, addr, asa_id):
        return
    sp = c.suggested_params()
    tx = ftxn.AssetOptInTxn(addr, sp, int(asa_id))
    txid = c.send_transaction(tx.sign(mnemonic.to_private_key(mn)))
    wait_for_confirmation(c, txid, 4)


def _prefund_router_if_needed(
    c, ctx: dict, app_id: int, *, min_target: int = 120_000
) -> None:
    app_addr = logic.get_application_address(int(app_id))
    have = _amount_or_zero(c, app_addr)
    if have >= int(min_target):
        return
    best = _best_funder_excluding(c, ctx, app_addr)
    if not best:
        # Not fatal; the outer AppCall may still cover inner fees if set high enough.
        return
    sp = c.suggested_params()
    seed_txn = ftxn.PaymentTxn(
        sender=best.addr, sp=sp, receiver=app_addr, amt=int(min_target) - have
    )
    txid = c.send_transaction(seed_txn.sign(mnemonic.to_private_key(best.mn)))
    wait_for_confirmation(c, txid, 4)


def _give_one_ticket(
    c, sender_mn: str, sender_addr: str, receiver_addr: str, asa_id: int
) -> None:
    """Send 1 unit of ASA from sender → receiver (assumes receiver opted-in)."""
    if asset_balance(c, receiver_addr, int(asa_id)) >= 1:
        return
    sp = c.suggested_params()
    ax = ftxn.AssetTransferTxn(
        sender=sender_addr, sp=sp, receiver=receiver_addr, amt=1, index=int(asa_id)
    )
    txid = c.send_transaction(ax.sign(mnemonic.to_private_key(sender_mn)))
    wait_for_confirmation(c, txid, 4)


def _auto_prepare_seller(c, ctx: dict, *, asa_id: int) -> None:
    """Ensure Seller is opted-in, funded, and holds 1 ticket (Creator → Seller)."""
    if not (ctx.get("seller_addr") and ctx.get("seller_mn")):
        raise RuntimeError("Seller wallet not configured.")
    if not (ctx.get("creator_addr") and ctx.get("creator_mn")):
        raise RuntimeError("Creator wallet not configured (needed to send 1 ticket).")

    # 1) Seller min balance for opt-in / fees
    _top_up_account(c, ctx, ctx["seller_addr"], min_target=200_000)

    # 2) Opt-in Seller to ASA
    _ensure_opt_in(c, ctx["seller_mn"], ctx["seller_addr"], int(asa_id))

    # 3) Send 1 ticket Creator → Seller (if not already holding)
    _give_one_ticket(
        c, ctx["creator_mn"], ctx["creator_addr"], ctx["seller_addr"], int(asa_id)
    )


def _auto_prepare_buyer(c, ctx: dict, *, price: int, asa_id: int) -> None:
    """Ensure Buyer is funded for price+fees and opted in to ASA."""
    if not (ctx.get("buyer_addr") and ctx.get("buyer_mn")):
        raise RuntimeError("Buyer wallet not configured.")

    # Fund buyer for price + safety (MBR + fees)
    min_needed = int(price) + int(MIN_BALANCE) + 10_000
    _top_up_account(c, ctx, ctx["buyer_addr"], min_target=min_needed)

    # Buyer opt-in
    _ensure_opt_in(c, ctx["buyer_mn"], ctx["buyer_addr"], int(asa_id))


def _auto_prepare_resale_parties(
    c,
    ctx: dict,
    *,
    holder_addr: str,
    holder_mn: str,
    newbuyer_addr: str,
    newbuyer_mn: str,
    price: int,
    asa_id: int,
) -> None:
    # Fund holder a little for their Axfer fee
    _top_up_account(c, ctx, holder_addr, min_target=120_000)
    # Fund new buyer for price + safety
    min_needed = int(price) + int(MIN_BALANCE) + 10_000
    _top_up_account(c, ctx, newbuyer_addr, min_target=min_needed)
    # Ensure new buyer opt-in
    _ensure_opt_in(c, newbuyer_mn, newbuyer_addr, int(asa_id))


# ============================== Main render ==================================


def render(ctx: dict) -> None:
    st.header("Buy / Resale (auto 1-click)")

    c = get_algod()
    ss = st.session_state

    # Quick helpers row
    col = st.columns(3)
    with col[0]:
        if st.button(
            "Use Last Router (creator)",
            disabled=not ctx.get("creator_addr"),
            use_container_width=True,
            key=k("trade", "use_last_router"),
        ):
            app_id = _load_last_router_id(c, ctx.get("creator_addr"))
            if not app_id:
                st.info("No Router apps found for this creator.")
            else:
                ss["TRADE_APP_ID"] = int(app_id)
                try:
                    gs = read_router_globals(c, int(app_id))
                    if isinstance(gs.get("asa"), int):
                        ss["TRADE_ASA_ID"] = int(gs["asa"])
                    st.success(f"Loaded Router #{app_id} (ASA {gs.get('asa', '—')})")
                except Exception:
                    st.success(f"Loaded Router #{app_id}")

    with col[1]:
        if st.button(
            "Buyer Opt-in to ASA",
            disabled=not (
                ctx.get("buyer_mn") and ctx.get("buyer_addr") and ss.get("TRADE_ASA_ID")
            ),
            use_container_width=True,
            key=k("trade", "buyer_optin"),
        ):
            try:
                _ensure_opt_in(
                    c, ctx["buyer_mn"], ctx["buyer_addr"], int(ss["TRADE_ASA_ID"])
                )
                st.success("Buyer opted-in.")
            except Exception as e:
                st.error(f"Opt-in failed: {e}")

    with col[2]:
        if st.button(
            "Prefund Router (0.2 ALGO)",
            disabled=not int(ss.get("TRADE_APP_ID", 0)),
            use_container_width=True,
            key=k("trade", "prefund_router_btn"),
        ):
            try:
                _prefund_router_if_needed(
                    c, ctx, int(ss["TRADE_APP_ID"]), min_target=200_000
                )
                st.success("Router prefunded.")
            except Exception as e:
                st.error(f"Prefund failed: {e}")

    st.markdown("---")

    # Shared inputs
    app_id, asa_id, price = _router_and_asa_inputs(ss)

    # =============================== PRIMARY BUY ==============================
    st.subheader("Primary Buy (Auto 1-click)")

    if st.button(
        "Run Buy (1-click: prepare + execute)",
        disabled=not (
            ctx.get("buyer_mn")
            and ctx.get("seller_mn")
            and int(app_id) > 0
            and int(asa_id) > 0
            and int(price) > 0
        ),
        use_container_width=True,
        key=k("trade", "buy_auto"),
    ):
        try:
            # Validate Router globals (including seller)
            gs = read_router_globals(c, int(app_id))
            _guard_router_globals_valid(gs, needs_seller=True)

            # Auto prep: Router, Seller, Buyer
            _prefund_router_if_needed(c, ctx, int(app_id), min_target=120_000)
            _auto_prepare_seller(c, ctx, asa_id=int(asa_id))
            _auto_prepare_buyer(c, ctx, price=int(price), asa_id=int(asa_id))

            # Build group [Payment, AppCall, Axfer]
            sp_pay = c.suggested_params()
            sp_app = c.suggested_params()
            sp_app.flat_fee = True
            sp_app.fee = max(APP_CALL_INNER_FEE, 3_000)  # BUY has 3 inner payments
            sp_axfer = c.suggested_params()

            app_addr = logic.get_application_address(int(app_id))
            pay = ftxn.PaymentTxn(
                sender=ctx["buyer_addr"], sp=sp_pay, receiver=app_addr, amt=int(price)
            )
            app_call = ftxn.ApplicationNoOpTxn(
                sender=ctx["buyer_addr"],
                sp=sp_app,
                index=int(app_id),
                app_args=[b"buy"],
                # accounts list not required by contract, but harmless:
                accounts=[gs["p1"], gs["p2"], gs["p3"], gs["seller"]],
            )
            axfer = ftxn.AssetTransferTxn(
                sender=ctx["seller_addr"],
                sp=sp_axfer,
                receiver=ctx["buyer_addr"],
                amt=1,
                index=int(asa_id),
            )

            gid = ftxn.calculate_group_id([pay, app_call, axfer])
            for t in (pay, app_call, axfer):
                t.group = gid

            txid = c.send_transactions(
                [
                    pay.sign(mnemonic.to_private_key(ctx["buyer_mn"])),
                    app_call.sign(mnemonic.to_private_key(ctx["buyer_mn"])),
                    axfer.sign(mnemonic.to_private_key(ctx["seller_mn"])),
                ]
            )
            resp = wait_for_confirmation(c, txid, 4)
            st.success(f"✅ Buy OK: {txid} | Round {resp['confirmed-round']}")
            # Remember last successful holder for 1-click resale
            st.session_state["LAST_HOLDER_ADDR"] = ctx["buyer_addr"]
        except Exception as e:
            st.error(f"Buy failed: {e}")

    st.markdown("---")

    # ================================= RESALE =================================
    st.subheader("Resale (Auto 1-click demo)")

    # Choose holder/new buyer for the demo automatically:
    demo_holder_addr = st.session_state.get("LAST_HOLDER_ADDR", ctx.get("buyer_addr"))
    demo_holder_mn = (
        ctx.get("buyer_mn") if demo_holder_addr == ctx.get("buyer_addr") else None
    )

    # Prefer Admin as the new buyer; fall back to Seller if Admin not set.
    demo_newbuyer_addr = ctx.get("admin_addr") or ctx.get("seller_addr")
    demo_newbuyer_mn = ctx.get("admin_mn") or ctx.get("seller_mn")

    st.caption(
        f"Holder: `{demo_holder_addr or '—'}` → New Buyer: `{demo_newbuyer_addr or '—'}` "
        "(auto-chosen for the demo: Holder=Buyer; New Buyer=Admin/Seller)"
    )

    if st.button(
        "Run Resale (1-click: prepare + execute)",
        disabled=not (
            int(app_id) > 0
            and int(asa_id) > 0
            and int(price) > 0
            and demo_holder_addr
            and demo_holder_mn
            and demo_newbuyer_addr
            and demo_newbuyer_mn
        ),
        use_container_width=True,
        key=k("trade", "resale_auto"),
    ):
        try:
            # Validate Router globals (payouts only needed)
            gs = read_router_globals(c, int(app_id))
            _guard_router_globals_valid(gs, needs_seller=False)

            # Auto prep: Router prefund, holder/new buyer funding & opt-in
            _prefund_router_if_needed(c, ctx, int(app_id), min_target=120_000)
            _auto_prepare_resale_parties(
                c,
                ctx,
                holder_addr=demo_holder_addr,
                holder_mn=demo_holder_mn,
                newbuyer_addr=demo_newbuyer_addr,
                newbuyer_mn=demo_newbuyer_mn,
                price=int(price),
                asa_id=int(asa_id),
            )

            # Guard seller actually owns 1 ticket
            if asset_balance(c, demo_holder_addr, int(asa_id)) < 1:
                raise RuntimeError("Holder does not own the ticket (cannot resale).")

            # Build group [Payment, AppCall, Axfer]
            sp_pay = c.suggested_params()
            sp_app = c.suggested_params()
            sp_app.flat_fee = True
            sp_app.fee = 2_000  # RESALE has 2 inner payments
            sp_axfer = c.suggested_params()

            app_addr = logic.get_application_address(int(app_id))
            pay = ftxn.PaymentTxn(
                sender=demo_newbuyer_addr, sp=sp_pay, receiver=app_addr, amt=int(price)
            )
            app_call = ftxn.ApplicationNoOpTxn(
                sender=demo_newbuyer_addr,
                sp=sp_app,
                index=int(app_id),
                app_args=[b"resale"],
                accounts=[gs["p1"], gs["p2"], gs["p3"], demo_holder_addr],
            )
            axfer = ftxn.AssetTransferTxn(
                sender=demo_holder_addr,
                sp=sp_axfer,
                receiver=demo_newbuyer_addr,
                amt=1,
                index=int(asa_id),
            )

            gid = ftxn.calculate_group_id([pay, app_call, axfer])
            for t in (pay, app_call, axfer):
                t.group = gid

            txid = c.send_transactions(
                [
                    pay.sign(mnemonic.to_private_key(demo_newbuyer_mn)),
                    app_call.sign(mnemonic.to_private_key(demo_newbuyer_mn)),
                    axfer.sign(mnemonic.to_private_key(demo_holder_mn)),
                ]
            )
            resp = wait_for_confirmation(c, txid, 4)
            st.success(f"✅ Resale OK: {txid} | Round {resp['confirmed-round']}")
            # Update last holder for next resale demo
            st.session_state["LAST_HOLDER_ADDR"] = demo_newbuyer_addr
        except Exception as e:
            st.error(f"Resale failed: {e}")
