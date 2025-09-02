# frontend/streamlit_app/core/state.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Session-scoped UI state helpers for the Streamlit operator console.

This module centralizes the **default values** we expect to exist in
`st.session_state` and provides a single entry point to initialize them.

Why this exists
---------------
- Streamlit widgets often read/write from `st.session_state`. If a key is
  missing (e.g., on first render or after a hot reload), downstream code can
  crash or show inconsistent UI.
- Keeping defaults in one place prevents "magic strings" scattered across
  pages and helps avoid typos. It also makes it easy to add/remove keys as
  the console grows.

Design notes
------------
- Defaults are intentionally **primitive** (ints) and safe to serialize.
  Avoid putting secrets or large objects in session state.
- Initialization is **idempotent**: calling `ensure_defaults()` multiple
  times is safe; existing values are preserved.

Usage
-----
Call `ensure_defaults()` once near the top of your Streamlit app (e.g., in
`app.py`), **before** pages read from `st.session_state`.

    from core.state import ensure_defaults
    ensure_defaults()

Extending
---------
To add a new session key, add it to `DEFAULTS` and reference the constant
key string from calling sites (or create a helper if you prefer).
"""

from collections.abc import Mapping
from typing import Final

import streamlit as st

# Canonical set of session keys and their initial values.
# Keep these aligned with the pages that consume them.
DEFAULTS: Final[Mapping[str, int]] = {
    # Most-recently created Ticket ASA identifier (used to prefill forms).
    "DEPLOY_ASA_ID": 0,
    # Royalty Router application id (active app the operator is working with).
    "TRADE_APP_ID": 0,
    # Ticket ASA id used for buy/resale flows.
    "TRADE_ASA_ID": 0,
    # Superfan application id for points/tiers and QR deep links.
    "SF_APP_ID": 0,
    # Current slide index for the staff screen carousel (persist across reruns).
    "STAFF_SLIDE": 0,
}

__all__ = ["DEFAULTS", "ensure_defaults"]


def ensure_defaults() -> None:
    """Ensure all expected session keys exist with sane defaults.

    Iterates through :data:`DEFAULTS` and sets each key in
    :data:`st.session_state` **only if** it is not already present. This
    preserves any values written by widgets or prior logic.

    This function is intentionally lightweight and safe to call on every rerun.

    Returns:
        None
    """
    for key, default_value in DEFAULTS.items():
        # Use setdefault to avoid stomping on values a user or widget has set.
        st.session_state.setdefault(key, default_value)
