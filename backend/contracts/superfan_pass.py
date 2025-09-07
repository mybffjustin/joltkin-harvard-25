# backend/contracts/superfan_pass.py
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


from pyteal import *

KEY_ADMIN = Bytes("admin")
KEY_POINTS = Bytes("pts")
KEY_TIER = Bytes("tier")

METHOD_ADD_POINTS = Bytes("add_points")
METHOD_CLAIM_TIER = Bytes("claim_tier")


def approval() -> Expr:
    on_create = Seq(
        Assert(Txn.application_args.length() >= Int(1)),
        # admin must be a raw address (32 bytes)
        Assert(Len(Txn.application_args[0]) == Int(32)),
        App.globalPut(KEY_ADMIN, Txn.application_args[0]),
        Approve(),
    )

    @Subroutine(TealType.none)
    def only_admin() -> Expr:
        return Assert(Txn.sender() == App.globalGet(KEY_ADMIN))

    points_to_add = ScratchVar(TealType.uint64)
    target_acct = ScratchVar(TealType.bytes)

    add_points = Seq(
        only_admin(),
        Assert(Txn.application_args.length() >= Int(2)),
        points_to_add.store(Btoi(Txn.application_args[1])),
        Assert(points_to_add.load() > Int(0)),
        If(Txn.accounts.length() > Int(0))
        .Then(target_acct.store(Txn.accounts[0]))
        .Else(target_acct.store(Txn.sender())),
        App.localPut(
            target_acct.load(),
            KEY_POINTS,
            App.localGet(target_acct.load(), KEY_POINTS) + points_to_add.load(),
        ),
        Approve(),
    )

    threshold = ScratchVar(TealType.uint64)
    claim_tier = Seq(
        Assert(Txn.application_args.length() >= Int(2)),
        threshold.store(Btoi(Txn.application_args[1])),
        Assert(threshold.load() > Int(0)),
        Assert(App.localGet(Txn.sender(), KEY_POINTS) >= threshold.load()),
        App.localPut(Txn.sender(), KEY_TIER, threshold.load()),
        Approve(),
    )

    handle_optin = Seq(
        App.localPut(Txn.sender(), KEY_POINTS, Int(0)),
        App.localPut(Txn.sender(), KEY_TIER, Int(0)),
        Approve(),
    )

    handle_noop = Seq(
        Assert(Txn.application_args.length() >= Int(1)),
        Cond(
            [Txn.application_args[0] == METHOD_ADD_POINTS, add_points],
            [Txn.application_args[0] == METHOD_CLAIM_TIER, claim_tier],
        ),
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.OptIn, handle_optin],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
        [
            Txn.on_completion() == OnComplete.UpdateApplication,
            Return(Txn.sender() == App.globalGet(KEY_ADMIN)),
        ],
        [
            Txn.on_completion() == OnComplete.DeleteApplication,
            Return(Txn.sender() == App.globalGet(KEY_ADMIN)),
        ],
    )
    return program


def clear() -> Expr:
    return Approve()


if __name__ == "__main__":
    print(compileTeal(approval(), mode=Mode.Application, version=8))
