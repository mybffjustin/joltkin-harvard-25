# frontend/streamlit_app/ui/keys.py
# SPDX-License-Identifier: Apache-2.0
"""Centralized helpers for Streamlit widget keys.

Why this exists
---------------
Streamlit widgets (e.g., st.text_input) require **stable** and **unique** keys
to preserve state across reruns and to avoid collisions—especially in apps with
multiple pages/tabs that may reuse similar control labels.

This module provides a single, tiny helper to standardize key construction and
minimize accidental collisions by **namespacing** every key with its page/scope.

Usage
-----
    from ui.keys import k

    show_code = st.text_input("Show code", key=k("venue", "show_code"))

Conventions
-----------
- `page` should be a short, stable namespace (e.g., "trade", "superfan",
  "venue", "harvard").
- `name` should be a concise, stable identifier for the specific widget within
  that page (e.g., "price_microalgos", "buyer_optin").
- Avoid user-provided strings for either parameter; prefer hardcoded literals.
"""

from __future__ import annotations


def k(page: str, name: str) -> str:
    """Return a stable, namespaced widget key.

    Streamlit derives an internal element ID from the widget type + parameters.
    Without an explicit key, similar widgets across different tabs/pages can
    collide and raise `StreamlitDuplicateElementId`. Namespacing keys with the
    page/scope prevents these collisions and keeps session state predictable.

    Args:
      page: Logical namespace for the widget (e.g., the page or tab name).
      name: Logical identifier for the widget within that namespace.

    Returns:
      A string of the form "<page>:<name>", suitable to pass as `key=...` to
      any Streamlit widget.

    Notes:
      - This function performs no validation or normalization; callers should
        pass simple ASCII identifiers (no whitespace) to keep keys readable.
      - If you need stronger guarantees (e.g., stripping spaces or enforcing a
        character set), consider wrapping this function or adding validation
        close to the callsite to avoid surprising changes to existing keys.
    """
    # Simple, deterministic concatenation yields stable keys and preserves
    # readability for debugging (e.g., inspecting st.session_state).
    return f"{page}:{name}"
