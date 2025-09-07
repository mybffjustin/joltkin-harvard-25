# backend/contracts/router.py
# SPDX-License-Identifier: Apache-2.0
# © 2025 Joltkin LLC.
#
# Royalty Router (PyTeal v8)
# - Primary “buy” splits proceeds to up to three payout addresses (P1/P2/P3)
# - Secondary “resale” pays a royalty to P1, remainder to current seller
#
# Group shapes (STRICT):
#   BUY:    G0 Payment (buyer -> app), G1 AppCall("buy"),    G2 Axfer (seller -> buyer, ASA, amt=1)
#   RESALE: G0 Payment (buyer -> app), G1 AppCall("resale"), G2 Axfer (curr seller -> buyer, ASA, amt=1)
#
# Inner tx counts (zero-fee):
#   BUY:    3 inner payments (P1, P2, P3)
#   RESALE: 2 inner payments (P1 royalty, seller remainder)
#
# NOTE: We do NOT send an extra “dust” payment to keep app balance at 0; this
# keeps BUY at exactly 3 inner transactions so your front-end fee (3000 µAlgos)
# remains correct. If you later want to flush rounding dust, require 4*min fee.

from pyteal import *

# ----------------------------- Global Keys -----------------------------------
P1 = Bytes("p1")  # bytes[32] payout 1 (artist)
P2 = Bytes("p2")  # bytes[32] payout 2
P3 = Bytes("p3")  # bytes[32] payout 3
BPS1 = Bytes("bps1")  # uint bps for p1 (0..10000)
BPS2 = Bytes("bps2")  # uint bps for p2
BPS3 = Bytes("bps3")  # uint bps for p3
ASA = Bytes("asa")  # uint ASA id
SELLER = Bytes("seller")  # bytes[32] canonical primary seller
ROY_BPS = Bytes("roybps")  # uint resale royalty bps (to P1)

ADDR_LEN = Int(32)
BPS_DENOM = Int(10_000)


def approval() -> Expr:
    """Approval program for the Royalty Router (TEAL v8)."""

    # ----------------------------- On Create ---------------------------------
    # Expect strictly-ordered args:
    #   0..2: p1, p2, p3 (BYTES, 32-byte raw public keys)
    #   3..5: bps1, bps2, bps3 (UINT)
    #   6   : roy_bps (UINT)
    #   7   : asa (UINT)
    #   8   : seller (BYTES, 32-byte raw public key)
    on_create = Seq(
        Assert(Txn.application_args.length() == Int(9)),
        # Basic shape checks so bad deployments fail fast
        Assert(Len(Txn.application_args[0]) == ADDR_LEN),
        Assert(Len(Txn.application_args[1]) == ADDR_LEN),
        Assert(Len(Txn.application_args[2]) == ADDR_LEN),
        Assert(Len(Txn.application_args[8]) == ADDR_LEN),
        # Store globals
        App.globalPut(P1, Txn.application_args[0]),
        App.globalPut(P2, Txn.application_args[1]),
        App.globalPut(P3, Txn.application_args[2]),
        App.globalPut(BPS1, Btoi(Txn.application_args[3])),
        App.globalPut(BPS2, Btoi(Txn.application_args[4])),
        App.globalPut(BPS3, Btoi(Txn.application_args[5])),
        App.globalPut(ROY_BPS, Btoi(Txn.application_args[6])),
        App.globalPut(ASA, Btoi(Txn.application_args[7])),
        App.globalPut(SELLER, Txn.application_args[8]),
        # Invariants
        Assert(App.globalGet(ASA) > Int(0)),
        Assert(
            (App.globalGet(BPS1) + App.globalGet(BPS2) + App.globalGet(BPS3))
            <= BPS_DENOM
        ),
        Approve(),
    )

    # --------------------------- Helpers / Hygiene ---------------------------
    def send_payment(receiver: Expr, amount: Expr) -> Expr:
        """Inner ALGO payment with zero inner fee."""
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: receiver,
                    TxnField.amount: amount,
                    TxnField.fee: Int(0),  # outer call covers fees
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    def _no_leaky_fields_payment(ti: Expr) -> Expr:
        """Disallow dangerous fields on outer Payment."""
        return Seq(
            Assert(Gtxn[ti].close_remainder_to() == Global.zero_address()),
            Assert(Gtxn[ti].rekey_to() == Global.zero_address()),
        )

    def _no_leaky_fields_axfer(ti: Expr) -> Expr:
        """Disallow dangerous fields on outer AssetTransfer."""
        return Seq(
            Assert(Gtxn[ti].asset_close_to() == Global.zero_address()),
            Assert(Gtxn[ti].rekey_to() == Global.zero_address()),
            # Optional: disallow clawback usage
            # Assert(Gtxn[ti].asset_sender() == Global.zero_address()),
        )

    pay_amt = ScratchVar(TealType.uint64)

    # ------------------------------- BUY -------------------------------------
    # EXPECTED GROUP:
    #   G0 Payment (buyer -> app)
    #   G1 AppCall("buy")
    #   G2 Axfer (seller -> buyer, ASA, amt=1)
    buy_p1 = ScratchVar(TealType.uint64)
    buy_p2 = ScratchVar(TealType.uint64)
    buy_p3 = ScratchVar(TealType.uint64)

    buy = Seq(
        Assert(Global.group_size() == Int(3)),
        Assert(Txn.group_index() == Int(1)),  # AppCall at index 1
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(3)),  # 3 inner payments
        # G0: payment into app
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        _no_leaky_fields_payment(Int(0)),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        pay_amt.store(Gtxn[0].amount()),
        # G2: seller -> buyer transfer of exactly 1 ASA
        Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
        _no_leaky_fields_axfer(Int(2)),
        Assert(Gtxn[2].xfer_asset() == App.globalGet(ASA)),
        Assert(Gtxn[2].asset_amount() == Int(1)),
        Assert(Gtxn[2].sender() == App.globalGet(SELLER)),
        Assert(Gtxn[2].asset_receiver() == Gtxn[0].sender()),
        # Compute splits
        buy_p1.store(WideRatio([pay_amt.load(), App.globalGet(BPS1)], [BPS_DENOM])),
        buy_p2.store(WideRatio([pay_amt.load(), App.globalGet(BPS2)], [BPS_DENOM])),
        buy_p3.store(WideRatio([pay_amt.load(), App.globalGet(BPS3)], [BPS_DENOM])),
        # Distribute (exactly 3 inner payments)
        send_payment(App.globalGet(P1), buy_p1.load()),
        send_payment(App.globalGet(P2), buy_p2.load()),
        send_payment(App.globalGet(P3), buy_p3.load()),
        Approve(),
    )

    # ------------------------------ RESALE -----------------------------------
    # EXPECTED GROUP:
    #   G0 Payment (buyer -> app)
    #   G1 AppCall("resale")
    #   G2 Axfer (current seller -> buyer, ASA, amt=1)
    roy_amt = ScratchVar(TealType.uint64)
    seller_amt = ScratchVar(TealType.uint64)

    resale = Seq(
        Assert(Global.group_size() == Int(3)),
        Assert(Txn.group_index() == Int(1)),  # AppCall at index 1
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),  # 2 inner payments
        # G0: payment into app
        Assert(Gtxn[0].type_enum() == TxnType.Payment),
        _no_leaky_fields_payment(Int(0)),
        Assert(Gtxn[0].receiver() == Global.current_application_address()),
        pay_amt.store(Gtxn[0].amount()),
        # G2: current holder -> buyer
        Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
        _no_leaky_fields_axfer(Int(2)),
        Assert(Gtxn[2].xfer_asset() == App.globalGet(ASA)),
        Assert(Gtxn[2].asset_amount() == Int(1)),
        Assert(Gtxn[2].asset_receiver() == Gtxn[0].sender()),
        # Split
        roy_amt.store(WideRatio([pay_amt.load(), App.globalGet(ROY_BPS)], [BPS_DENOM])),
        seller_amt.store(pay_amt.load() - roy_amt.load()),
        # Pay out (exactly 2 inner payments)
        send_payment(App.globalGet(P1), roy_amt.load()),
        send_payment(Gtxn[2].sender(), seller_amt.load()),
        Approve(),
    )

    # --------------------------- NoOp Dispatcher -----------------------------
    handle_noop = Cond(
        [Txn.application_args[0] == Bytes("buy"), buy],
        [Txn.application_args[0] == Bytes("resale"), resale],
    )

    # ------------------------------ Lifecycle --------------------------------
    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
        [
            Txn.on_completion() == OnComplete.DeleteApplication,
            Return(Txn.sender() == Global.creator_address()),
        ],
        [
            Txn.on_completion() == OnComplete.UpdateApplication,
            Return(Txn.sender() == Global.creator_address()),
        ],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.on_completion() == OnComplete.OptIn, Approve()],
    )

    return program


def clear() -> Expr:
    """Clear-state program (always approve)."""
    return Approve()


if __name__ == "__main__":
    print(compileTeal(approval(), mode=Mode.Application, version=8))
