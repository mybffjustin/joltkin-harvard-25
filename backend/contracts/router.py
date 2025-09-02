# backend/contracts/router.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions
# and limitations under the License.

"""
Royalty Router smart contract (PyTeal v8).

This application routes primary sale revenue to up to three payout addresses and
handles secondary sales by paying an artist royalty and returning the remainder
to the current seller.

Two entrypoints (NoOp calls with an arg selector) are supported:

1) "buy"    — Primary sale:
              Group of 3:
                0: ApplicationCall (this app) with arg "buy"
                1: Payment       (buyer -> app address)           [ALGO]
                2: AssetTransfer (seller -> buyer)                 [ASA]
              Effect: ALGO sent to app is split to P1/P2/P3 per basis points.

2) "resale" — Secondary sale:
              Group of 3:
                0: ApplicationCall (this app) with arg "resale"
                1: Payment       (buyer -> app address)           [ALGO]
                2: AssetTransfer (current seller -> buyer)        [ASA]
              Effect: ALGO is split into royalty (to P1) + remainder (to seller).

Design goals:
  * Keep invariants explicit and auditable (e.g., BPS sum <= 10000).
  * Ensure atomicity by validating full group shape and indices.
  * Avoid fee leakage by setting inner-txn fee = 0 (caller must cover fees).
  * Use WideRatio for safe 64-bit products/quotients.

Security notes:
  * This contract assumes the external group enforces correct price amounts and
    optional policy (e.g., min price). If needed, add args to validate.
  * We do not validate close_to/rekey/fv/… in the outer txns here — callers
    should keep them default. Consider adding explicit Asserts if your policy
    requires it.
  * App stores addresses and bps at creation; only creator may Update/Delete.

Gas/fees:
  * "buy" sends 3 inner payments → caller must provision at least 3 * min fee.
  * "resale" sends 2 inner payments → caller must provision at least 2 * min fee.
"""

from pyteal import *

# ----------------------------- Global Keys -----------------------------------
# All global state keys. Keep names short to minimize on-chain footprint.

P1 = Bytes("p1")  # payout address 1 (e.g., artist)
P2 = Bytes("p2")  # payout address 2 (e.g., venue/label)
P3 = Bytes("p3")  # payout address 3 (e.g., DAO/crew)

BPS1 = Bytes("bps1")  # basis points for p1 (0..10000)
BPS2 = Bytes("bps2")  # basis points for p2
BPS3 = Bytes("bps3")  # basis points for p3

ASA = Bytes("asa")  # ASA id (uint64) for the ticket/membership NFT (amount=1)
SELLER = Bytes("seller")  # canonical seller/treasury for primary sale

ROY_BPS = Bytes("roybps")  # artist royalty bps for secondary sales (0..10000)


def approval() -> Expr:
    """Builds the approval program.

    Returns:
        Expr: The PyTeal expression for the approval logic.
    """

    # ----------------------------- On Create ---------------------------------
    # App creation initializes immutable parameters for splits and addresses.
    on_create = Seq(
        # Expect 9 args in strict order:
        #   0..2: P1,P2,P3 (bytes addresses)
        #   3..5: BPS1,BPS2,BPS3 (uint64, basis points)
        #   6:    ROY_BPS       (uint64, basis points for resale)
        #   7:    ASA           (uint64, asset id)
        #   8:    SELLER        (bytes address)
        Assert(Txn.application_args.length() == Int(9)),
        # Install addresses.
        App.globalPut(P1, Txn.application_args[0]),
        App.globalPut(P2, Txn.application_args[1]),
        App.globalPut(P3, Txn.application_args[2]),
        # Install basis points (convert from bytes -> uint64).
        App.globalPut(BPS1, Btoi(Txn.application_args[3])),
        App.globalPut(BPS2, Btoi(Txn.application_args[4])),
        App.globalPut(BPS3, Btoi(Txn.application_args[5])),
        # Install resale royalty bps and ASA id.
        App.globalPut(ROY_BPS, Btoi(Txn.application_args[6])),
        App.globalPut(ASA, Btoi(Txn.application_args[7])),
        # Install canonical primary SELLER/treasury.
        App.globalPut(SELLER, Txn.application_args[8]),
        Approve(),
    )

    # Validate that cumulative BPS do not exceed 100% (10000 bps).
    valid_bps = (
        App.globalGet(BPS1) + App.globalGet(BPS2) + App.globalGet(BPS3)
    ) <= Int(10000)

    def send_payment(receiver: Expr, amount: Expr) -> Expr:
        """Inner ALGO payment with zero fee.

        Args:
            receiver: Receiver address (bytes).
            amount: MicroAlgos amount (uint64).

        Returns:
            Expr: Sequence that submits the inner payment.
        """
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: receiver,
                    TxnField.amount: amount,
                    # Fee is paid by the outer application call, not this inner txn.
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    # Scratch variable reused for computing distributions.
    pay_amt = ScratchVar(TealType.uint64)

    # ------------------------------- buy() -----------------------------------
    # Primary sale:
    #   G0: AppCall("buy")
    #   G1: Payment (buyer -> app)  : price ALGO
    #   G2: ASA xfer (seller -> buyer) amount=1, asset=ASA
    buy = Seq(
        # Sanity checks for configured split.
        Assert(valid_bps),
        # Group structure & fee provisioning:
        Assert(Global.group_size() == Int(3)),
        Assert(Txn.group_index() == Int(0)),
        # Outer AppCall must carry fees for 3 inner payments in this path.
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(3)),
        # (G1) Buyer pays the app address (escrow).
        Assert(Gtxn[1].type_enum() == TxnType.Payment),
        Assert(Gtxn[1].receiver() == Global.current_application_address()),
        pay_amt.store(Gtxn[1].amount()),
        # (G2) Seller transfers the ASA (ticket/NFT) to the buyer.
        Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[2].xfer_asset() == App.globalGet(ASA)),
        Assert(Gtxn[2].asset_amount() == Int(1)),
        Assert(Gtxn[2].sender() == App.globalGet(SELLER)),
        # Asset receiver must be the buyer (the payer in G1).
        Assert(Gtxn[2].asset_receiver() == Gtxn[1].sender()),
        # Distribute proceeds to P1/P2/P3 per basis points.
        send_payment(
            App.globalGet(P1),
            WideRatio([pay_amt.load(), App.globalGet(BPS1)], [Int(10000)]),
        ),
        send_payment(
            App.globalGet(P2),
            WideRatio([pay_amt.load(), App.globalGet(BPS2)], [Int(10000)]),
        ),
        send_payment(
            App.globalGet(P3),
            WideRatio([pay_amt.load(), App.globalGet(BPS3)], [Int(10000)]),
        ),
        Approve(),
    )

    # ----------------------------- resale() ----------------------------------
    # Secondary sale:
    #   G0: AppCall("resale")
    #   G1: Payment (buyer -> app)  : resale price ALGO
    #   G2: ASA xfer (current seller -> buyer) amount=1, asset=ASA
    #
    # Royalty is paid to P1. Remaining proceeds go to the current seller
    # (i.e., the sender of the asset transfer in G2).
    seller_amt = ScratchVar(TealType.uint64)
    roy_amt = ScratchVar(TealType.uint64)

    resale = Seq(
        # Group structure & fee provisioning:
        Assert(Global.group_size() == Int(3)),
        Assert(Txn.group_index() == Int(0)),
        # Two inner payments (royalty + seller).
        Assert(Txn.fee() >= Global.min_txn_fee() * Int(2)),
        # (G1) Buyer pays the app address (escrow).
        Assert(Gtxn[1].type_enum() == TxnType.Payment),
        Assert(Gtxn[1].receiver() == Global.current_application_address()),
        pay_amt.store(Gtxn[1].amount()),
        # (G2) Current holder transfers ASA to buyer.
        Assert(Gtxn[2].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[2].xfer_asset() == App.globalGet(ASA)),
        Assert(Gtxn[2].asset_amount() == Int(1)),
        Assert(Gtxn[2].asset_receiver() == Gtxn[1].sender()),
        # Compute royalty and seller remainder.
        roy_amt.store(
            WideRatio([pay_amt.load(), App.globalGet(ROY_BPS)], [Int(10000)])
        ),
        seller_amt.store(pay_amt.load() - roy_amt.load()),
        # Pay artist royalty to P1.
        send_payment(App.globalGet(P1), roy_amt.load()),
        # Pay remainder to current seller (the sender of the ASA xfer in G2).
        send_payment(Gtxn[2].sender(), seller_amt.load()),
        Approve(),
    )

    # --------------------------- NoOp Dispatcher -----------------------------
    # Dispatch based on first argument for NoOp calls.
    handle_noop = Cond(
        [Txn.application_args[0] == Bytes("buy"), buy],
        [Txn.application_args[0] == Bytes("resale"), resale],
    )

    # ------------------------------ Lifecycle --------------------------------
    # Classic application lifecycle handling.
    program = Cond(
        # Create
        [Txn.application_id() == Int(0), on_create],
        # NoOp (entrypoints)
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
        # Update/Delete only by creator.
        [
            Txn.on_completion() == OnComplete.DeleteApplication,
            Return(Txn.sender() == Global.creator_address()),
        ],
        [
            Txn.on_completion() == OnComplete.UpdateApplication,
            Return(Txn.sender() == Global.creator_address()),
        ],
        # OptIn/CloseOut: stateless (no local state), allow freely.
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.on_completion() == OnComplete.OptIn, Approve()],
    )

    return program


def clear() -> Expr:
    """Builds the clear-state program (always approve).

    Returns:
        Expr: The PyTeal expression for clear-state logic.
    """
    return Approve()


# ------------------------------- Developer Tips -------------------------------
# * Consider adding additional Asserts if your policy requires hardening:
#   - Assert(Gtxn[1].close_remainder_to() == Global.zero_address())
#   - Assert(Gtxn[1].rekey_to() == Global.zero_address())
#   - Assert(Gtxn[2].asset_close_to() == Global.zero_address())
#   - Assert(Gtxn[2].rekey_to() == Global.zero_address())
#   - Assert(Gtxn[2].asset_sender() == Global.zero_address())  # disallow clawback
#
# * If you need a minimum/maximum price policy, pass it as an app arg and Assert
#   against Gtxn[1].amount().
#
# * For primary sale, this contract trusts the provided SELLER address. If you
#   want to enforce that the ASA actually originated from SELLER (e.g., minted
#   or still held), consider adding separate on-chain checks or setup flows.
#
# * For royalties on non-custodial secondary markets, ensure integrators follow
#   the required group shape; otherwise royalty payments cannot be enforced.
#
# * Always update version pin (Mode.Application, version=8) in the compiler call
#   when adopting newer PyTeal/TEAL features.

if __name__ == "__main__":
    # Compile the program for deployment. Ensure TEAL v8 (or your target) is supported
    # by your network. The output can be written to a file by redirecting stdout.
    print(compileTeal(approval(), mode=Mode.Application, version=8))
