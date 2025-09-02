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
# =============================================================================
# Superfan Pass (PyTeal)
# -----------------------------------------------------------------------------
# Minimal loyalty contract for demos:
# - Local state keys:
#     "pts"  : uint64 points accumulated by a user
#     "tier" : uint64 - user-set tier, gated by minimum points threshold
# - Global state:
#     "admin": bytes, the single admin address authorized to add points to others
#
# Entry points:
# - On create:   store admin (passed in via application args[0])
# - Opt-in:      initialize local keys pts=0, tier=0
# - NoOp "add_points <amount> [account]":
#       If a foreign account is provided in Txn.accounts[0], add points to that
#       account's local state; otherwise add points to the caller (self-award).
#       Only admin may call this method.
# - NoOp "claim_tier <threshold>":
#       Caller sets their local "tier" to <threshold> if they have >= threshold points.
#
# Security/Defensive notes:
# - Validate method arg counts and types (e.g., ensure an amount is provided).
# - Restrict update/delete to admin only.
# - Use clear, consistent state keys via module-level constants.
# - Avoid off-by-one on Txn.accounts[] indexing (index 0 is the first foreign account).
#
# This contract targets TEAL v8 semantics.
# =============================================================================

from pyteal import *

# -------------------------------
# Constants (Global & Local Keys)
# -------------------------------

# Global keys
KEY_ADMIN = Bytes("admin")

# Local keys
KEY_POINTS = Bytes("pts")
KEY_TIER = Bytes("tier")

# Method selectors (string constants for readability)
METHOD_ADD_POINTS = Bytes("add_points")
METHOD_CLAIM_TIER = Bytes("claim_tier")


def approval() -> Expr:
    """
    Program approval (stateful application).
    Defines create/optin/noop/closeout/update/delete handlers.
    """

    # -------------------------------------------------------------------------
    # On Create: store admin address in global state
    # args[0] = admin address (as bytes)
    # -------------------------------------------------------------------------
    on_create = Seq(
        # Require at least one argument for the admin address.
        Assert(Txn.application_args.length() >= Int(1)),
        App.globalPut(KEY_ADMIN, Txn.application_args[0]),
        Approve(),
    )

    # -------------------------------------------------------------------------
    # Helper: admin check
    # -------------------------------------------------------------------------
    @Subroutine(TealType.none)
    def assert_only_admin() -> Expr:
        """Assert that the transaction sender is the stored admin."""
        return Assert(Txn.sender() == App.globalGet(KEY_ADMIN))

    # -------------------------------------------------------------------------
    # NoOp: add_points <amount> [target_account]
    #
    # Behavior:
    # - Only admin may call.
    # - Points added = Btoi(args[1]).
    # - Target:
    #     * If at least one foreign account is provided, use Txn.accounts[0].
    #     * Otherwise, default to Txn.sender() (self-award).
    #
    # Rationale:
    # Streamlit issues:
    #   ApplicationNoOpTxn(
    #       sender=admin,
    #       app_args=[b"add_points", amount_bytes],
    #       accounts=[buyer_addr],    # <- first foreign account is index 0
    #   )
    # Therefore, referencing Txn.accounts[0] is correct.
    # -------------------------------------------------------------------------
    points_to_add = ScratchVar(TealType.uint64)
    target_acct = ScratchVar(TealType.bytes)

    add_points = Seq(
        assert_only_admin(),
        # We expect at least 2 args: method, amount
        Assert(Txn.application_args.length() >= Int(2)),
        points_to_add.store(Btoi(Txn.application_args[1])),
        # Optional: disallow zero-point mutations (keeps history meaningful)
        # Comment out the next line if you want to allow 0.
        Assert(points_to_add.load() > Int(0)),
        # Choose target account: first foreign account if provided, else sender.
        If(Txn.accounts.length() > Int(0))
        .Then(target_acct.store(Txn.accounts[0]))
        .Else(target_acct.store(Txn.sender())),
        # Update local "pts" on target account (missing key reads as 0 by default).
        App.localPut(
            target_acct.load(),
            KEY_POINTS,
            App.localGet(target_acct.load(), KEY_POINTS) + points_to_add.load(),
        ),
        Approve(),
    )

    # -------------------------------------------------------------------------
    # NoOp: claim_tier <threshold>
    #
    # Behavior:
    # - Caller (Txn.sender) sets local "tier" to threshold if they have >= threshold points.
    # - This makes tier client-controlled but gated by on-chain points.
    # -------------------------------------------------------------------------
    threshold = ScratchVar(TealType.uint64)

    claim_tier = Seq(
        # We expect at least 2 args: method, threshold
        Assert(Txn.application_args.length() >= Int(2)),
        threshold.store(Btoi(Txn.application_args[1])),
        # Optional: enforce positive threshold
        Assert(threshold.load() > Int(0)),
        # Require that the caller has sufficient points.
        Assert(App.localGet(Txn.sender(), KEY_POINTS) >= threshold.load()),
        # Set the caller's tier to the threshold. You can cap or map tiers off-chain if desired.
        App.localPut(Txn.sender(), KEY_TIER, threshold.load()),
        Approve(),
    )

    # -------------------------------------------------------------------------
    # On Opt-In: initialize local state for the caller
    # -------------------------------------------------------------------------
    handle_optin = Seq(
        App.localPut(Txn.sender(), KEY_POINTS, Int(0)),
        App.localPut(Txn.sender(), KEY_TIER, Int(0)),
        Approve(),
    )

    # -------------------------------------------------------------------------
    # NoOp dispatcher
    # -------------------------------------------------------------------------
    handle_noop = Seq(
        # Must have at least a selector in args[0]
        Assert(Txn.application_args.length() >= Int(1)),
        Cond(
            [Txn.application_args[0] == METHOD_ADD_POINTS, add_points],
            [Txn.application_args[0] == METHOD_CLAIM_TIER, claim_tier],
        ),
    )

    # -------------------------------------------------------------------------
    # Top-level program dispatcher (OnCompletion)
    # -------------------------------------------------------------------------
    program = Cond(
        # Create
        [Txn.application_id() == Int(0), on_create],
        # Opt-In / CloseOut
        [Txn.on_completion() == OnComplete.OptIn, handle_optin],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        # NoOp (method calls)
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
        # Update / Delete restricted to admin
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
    """
    Clear-state program.
    Do not block user from clearing local state; nothing to clean up.
    """
    return Approve()


# -----------------------------------------------------------------------------
# Local test / CLI compile
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print(compileTeal(approval(), mode=Mode.Application, version=8))
    # For completeness, you can also print the clear program if desired:
    # print(compileTeal(clear(), mode=Mode.Application, version=8))
