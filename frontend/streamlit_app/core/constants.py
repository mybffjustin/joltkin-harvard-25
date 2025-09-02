# frontend/streamlit_app/core/constants.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Algorand economics constants and Harvard-specific lookup tables.

This module centralizes:
  1) **Protocol economics** used across the UI (e.g., Minimum Balance
     Requirements and typical inner transaction fee guidance).
  2) **Harvard Houses / First-Year Dorms** canonical names plus common
     synonyms and normalization helpers for user input.

Design notes
------------
- Constants are typed `Final[int]` to communicate immutability and to help
  static analyzers catch accidental reassignment.
- Normalization helpers are intentionally lightweight and allocation-friendly:
  they trim and collapse whitespace, Title-Case the string, then consult a
  small in-memory mapping. No I/O or heavy dependencies.
- Canonical lists are kept in **Title Case** to align with how names are
  typically presented on-campus and in marketing materials.

Caveats
-------
- Fee guidance (e.g., `APP_CALL_INNER_FEE`) is a *typical* value for demo
  flows. Production apps should compute fees precisely based on the *actual*
  number of inner transactions and protocol parameters in effect.
- Synonym maps are not exhaustive; expand as your use-cases require.
"""

from typing import Final

# ---------------------------------------------------------------------------
# Algorand economics (microAlgos). Values chosen for clarity in demos.
# ---------------------------------------------------------------------------

#: Account **Minimum Balance Requirement** (MBR). At the time of writing,
#: 100_000 µAlgos is the baseline MBR for an empty account. Additional
#: holdings (assets, apps, local state) add to this baseline.
MIN_BALANCE: Final[int] = 100_000

#: **Asset (ASA) holding MBR** per asset slot held by an account. If a wallet
#: opts into an ASA, its MBR increases by this amount.
ASSET_MBR: Final[int] = 100_000

#: **Application local state MBR** per app opted-in by an account. If a wallet
#: opts into an application, its MBR increases by this amount.
APP_LOCAL_MBR: Final[int] = 100_000

#: A *typical* flat fee (µAlgos) to cover inner transactions performed by an
#: application call in these demos. The exact fee depends on inner txn count
#: and protocol costs—prefer computing precisely in production.
APP_CALL_INNER_FEE: Final[int] = 4_000

# ---------------------------------------------------------------------------
# Harvard canonical names + synonyms
# ---------------------------------------------------------------------------

#: Canonical list of **upper-class Houses** in Title Case. Keep ordering stable
#: for predictable UI presentation and print pack generation.
HARVARD_HOUSES: list[str] = [
    "Adams",
    "Cabot",
    "Currier",
    "Dudley Community",
    "Dunster",
    "Eliot",
    "Kirkland",
    "Leverett",
    "Lowell",
    "Mather",
    "Pforzheimer",
    "Quincy",
    "Winthrop",
]

#: Common short-hands → canonical House names.
#: Keys are expected in Title Case after normalization.
HOUSE_SYNONYMS: dict[str, str] = {
    "Pfoho": "Pforzheimer",
    "Pfoz": "Pforzheimer",
    "Dudley": "Dudley Community",
    "Dudley House": "Dudley Community",
}

#: Canonical list of **first-year dorms** in Title Case (Yard).
FIRST_YEAR_DORMS: list[str] = [
    "Apley Court",
    "Canaday Hall",
    "Grays Hall",
    "Greenough Hall",
    "Hollis Hall",
    "Holworthy Hall",
    "Hurlbut Hall",
    "Lionel Hall",
    "Matthews Hall",
    "Massachusetts Hall",
    "Mower Hall",
    "Pennypacker Hall",
    "Stoughton Hall",
    "Straus Hall",
    "Thayer Hall",
    "Weld Hall",
    "Wigglesworth Hall",
]

#: Common short-hands → canonical first-year dorm names.
#: Keys are expected in Title Case after normalization.
DORM_SYNONYMS: dict[str, str] = {
    "Apley": "Apley Court",
    "Canaday": "Canaday Hall",
    "Grays": "Grays Hall",
    "Greenough": "Greenough Hall",
    "Hollis": "Hollis Hall",
    "Holworthy": "Holworthy Hall",
    "Hurlbut": "Hurlbut Hall",
    "Lionel": "Lionel Hall",
    "Matthews": "Matthews Hall",
    "Mass Hall": "Massachusetts Hall",
    "Massachusetts": "Massachusetts Hall",
    "Mower": "Mower Hall",
    "Pennypacker": "Pennypacker Hall",
    "Stoughton": "Stoughton Hall",
    "Straus": "Straus Hall",
    "Thayer": "Thayer Hall",
    "Weld": "Weld Hall",
    "Wigg": "Wigglesworth Hall",
    "Wigglesworth": "Wigglesworth Hall",
}

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def normalize_house(name: str) -> str:
    """
    Normalize a user-provided House string to its canonical form.

    The function:
      1) Trims leading/trailing whitespace.
      2) Collapses internal whitespace to single spaces.
      3) Title-Cases the result (e.g., "pfoho" → "Pfoho").
      4) Maps common short-hands to canonical names using `HOUSE_SYNONYMS`.

    If no mapping applies, returns the normalized string as-is.

    Args:
        name: Raw input (possibly empty or oddly cased).

    Returns:
        Canonical House name in Title Case, or the best-effort normalized input.

    Examples:
        >>> normalize_house("  pfoho ")
        'Pforzheimer'
        >>> normalize_house("Dudley")
        'Dudley Community'
        >>> normalize_house("Lowell")
        'Lowell'
    """
    # Cheap sanitation: strip and collapse whitespace; normalize case.
    n = " ".join((name or "").strip().split()).title()
    # Apply synonym mapping; fall back to the normalized token.
    return HOUSE_SYNONYMS.get(n, n)


def normalize_first_year_dorm(name: str) -> str:
    """
    Normalize a user-provided first-year dorm string to its canonical form.

    The function:
      1) Trims/collapses whitespace and Title-Cases the input.
      2) If the result is already a canonical dorm name, return it.
      3) Otherwise, consult `DORM_SYNONYMS` for a mapping.
      4) If neither applies, return the best-effort normalized input.

    Args:
        name: Raw input (arbitrary casing/spacing).

    Returns:
        Canonical dorm name in Title Case, or the best-effort normalized input.

    Examples:
        >>> normalize_first_year_dorm("  wigg ")
        'Wigglesworth Hall'
        >>> normalize_first_year_dorm("Mass hall")
        'Massachusetts Hall'
        >>> normalize_first_year_dorm("Thayer Hall")
        'Thayer Hall'
    """
    n = " ".join((name or "").strip().split()).title()
    return n if n in FIRST_YEAR_DORMS else DORM_SYNONYMS.get(n, n)
