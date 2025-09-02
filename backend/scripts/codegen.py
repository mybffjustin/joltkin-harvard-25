# backend/scripts/codegen.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Joltkin LLC.
#
# Purpose
# -------
# Generate fresh **TestNet** accounts for common project roles and write their
# 25-word mnemonics into a `.env` file as:
#   CREATOR_MNEMONIC="..."
#   SELLER_MNEMONIC="..."
#   BUYER_MNEMONIC="..."
#   ADMIN_MNEMONIC="..."
#
# Safety
# ------
# • This script **overwrites** existing *_MNEMONIC entries in `.env`.
# • Mnemonics grant full control of funds. Treat `.env` as a secret
#   (add to .gitignore, restrict file permissions).
# • We **do not print mnemonics** to stdout by default—only addresses.
#   Use `--print-secrets` if you explicitly want them echoed (not recommended).
#
# Behavior
# --------
# • Backs up an existing .env to `.env.bak.YYYYMMDD-HHMMSS` (configurable).
# • Removes any existing lines containing `_MNEMONIC=` before appending new ones.
# • Writes atomically (temp file + rename) and sets file mode to 0600.

from __future__ import annotations

import argparse
import datetime as _dt
import os
import stat
import tempfile
from collections.abc import Iterable
from pathlib import Path

from algosdk import account, mnemonic

# Default set of project roles for which we create accounts.
DEFAULT_ROLES: tuple[str, ...] = ("CREATOR", "SELLER", "BUYER", "ADMIN")


def generate_accounts(roles: Iterable[str]) -> dict[str, tuple[str, str]]:
    """
    Generate (address, mnemonic) pairs for each role.

    Returns:
      dict mapping ROLE -> (address, mnemonic)

    Notes:
      - Private keys exist only transiently in memory; we do not persist them.
      - Callers are responsible for writing mnemonics to secure storage.
    """
    out: dict[str, tuple[str, str]] = {}
    for role in roles:
        sk, addr = account.generate_account()
        m = mnemonic.from_private_key(sk)
        out[role] = (addr, m)
    return out


def read_text(path: Path) -> str:
    """Read file text with UTF-8 if it exists; otherwise return empty string."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


def strip_existing_mnemonics(env_text: str) -> str:
    """
    Remove lines that define any *_MNEMONIC=... entries.

    We keep other lines (comments, ALGOD config, etc.) verbatim.
    Empty lines are also trimmed to avoid accumulating whitespace.
    """
    keep: list[str] = []
    for ln in env_text.splitlines():
        if "_MNEMONIC=" in ln:
            # Drop prior mnemonic line(s)
            continue
        if ln.strip() == "":
            # Skip pure blank lines to keep file tidy
            continue
        keep.append(ln)
    return "\n".join(keep).rstrip() + ("\n" if keep else "")


def write_env_atomic(path: Path, text: str) -> None:
    """
    Atomically write `text` to `path`:
      - write to a temporary file in the same directory
      - fsync and os.replace for atomic swap
      - set restrictive permissions (0600)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name

    # Replace target atomically and lock down permissions
    os.replace(temp_name, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def backup_env(path: Path) -> Path:
    """
    If `path` exists, create a timestamped backup alongside it.
    Returns the backup path (or the would-be path if original didn't exist).
    """
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak.{stamp}")
    if path.exists():
        bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return bak


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TestNet accounts and write *_MNEMONIC entries to .env",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to .env file to update",
    )
    parser.add_argument(
        "--roles",
        type=str,
        default=",".join(DEFAULT_ROLES),
        help="Comma-separated roles to generate (names become <ROLE>_MNEMONIC keys)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped .env backup before writing",
    )
    parser.add_argument(
        "--print-secrets",
        action="store_true",
        help="Also print mnemonics to stdout (NOT RECOMMENDED)",
    )
    args = parser.parse_args()

    roles = [r.strip().upper() for r in args.roles.split(",") if r.strip()]
    if not roles:
        raise SystemExit("No roles specified")

    # 1) Generate fresh accounts
    generated = generate_accounts(roles)

    # 2) Print addresses (safe to display). Only print mnemonics if explicitly requested.
    print("Generated TestNet accounts:")
    for role in roles:
        addr, m = generated[role]
        print(f"  {role}_ADDR = {addr}")
        if args.print_secrets:
            print(f"  {role}_MNEMONIC = {m}")

    # 3) Prepare .env content: keep existing lines except *_MNEMONIC, then append new secrets.
    existing = read_text(args.env)
    cleansed = strip_existing_mnemonics(existing)
    appended_lines = "".join(
        f'{role}_MNEMONIC="{generated[role][1]}"\n' for role in roles
    )
    new_env_text = cleansed + appended_lines

    # 4) Optional backup for safety
    if not args.no_backup and args.env.exists():
        bak = backup_env(args.env)
        print(f"\nBackup created: {bak.name}")

    # 5) Atomic write with restrictive permissions
    write_env_atomic(args.env, new_env_text)

    # 6) Final guidance
    print(f"\nWrote {len(roles)} fresh 25-word mnemonics to {args.env} (TestNet).")
    print("IMPORTANT:")
    print("  • Fund the addresses via TestNet faucet before transacting.")
    print("  • Keep .env out of version control and restrict access (chmod 600).")


if __name__ == "__main__":
    main()
