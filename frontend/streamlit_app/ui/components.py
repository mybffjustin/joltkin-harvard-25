# frontend/streamlit_app/ui/components.py
# SPDX-License-Identifier: Apache-2.0
"""Reusable Streamlit UI components.

This module intentionally keeps dependencies minimal and focuses on small,
well-tested presentation helpers that can be imported across pages.

Currently provided:
  • table_ranked_wallets(): Render a compact, ranked leaderboard of wallets.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import streamlit as st

# How many characters to show from the start/end of an address when eliding.
_ADDR_PREFIX = 6
_ADDR_SUFFIX = 4


def _short_addr(
    addr: str, *, prefix: int = _ADDR_PREFIX, suffix: int = _ADDR_SUFFIX
) -> str:
    """Return a human-friendly shortened form of a wallet address.

    Examples:
      "ABCD12…WXYZ" for a typical Algorand 58-char address.

    Args:
      addr: Full address string.
      prefix: Number of leading characters to retain.
      suffix: Number of trailing characters to retain.

    Returns:
      A shortened representation. If the address is already short, it is
      returned unchanged. None/empty inputs yield "—" (em dash).
    """
    if not addr:
        return "—"
    if len(addr) <= prefix + suffix + 1:
        return addr
    return f"{addr[:prefix]}…{addr[-suffix:]}"


def table_ranked_wallets(
    rows: Sequence[tuple[str, int, int]] | Iterable[tuple[str, int, int]],
) -> None:
    """Render a static table of ranked wallets (Address, Points, Tier).

    This is designed for small leaderboards (≤ 50 rows). For larger, consider
    `st.dataframe` to benefit from virtualization and interactive sorting.

    Args:
      rows: Iterable of (address, points, tier). Order is preserved and a 1-based
        "Rank" column is added.

    Behavior:
      - Addresses are abbreviated for readability.
      - Points are displayed with thousands separators.
      - Empty input renders a friendly info message instead of an empty table.
    """
    # Normalize to a list so we can enumerate twice without exhausting an iterator.
    rows_list = list(rows or [])
    if not rows_list:
        st.info("No results yet. Run a scan or add points to populate the leaderboard.")
        return

    # Build table records with defensive coercion.
    table_records = []
    for i, (addr, points, tier) in enumerate(rows_list, start=1):
        # Best-effort coercion/validation to keep the UI resilient.
        try:
            p = max(0, int(points))
        except Exception:
            p = 0
        try:
            t = max(0, int(tier))
        except Exception:
            t = 0

        table_records.append(
            {
                "Rank": i,
                "Address": _short_addr(str(addr)),
                "Points": f"{p:,}",  # thousands separators for readability
                "Tier": t,
            }
        )

    # `st.table` renders a static table that respects key order in dicts.
    # For interactive features (sort/filter), swap to `st.dataframe(table_records)`.
    st.table(table_records)
