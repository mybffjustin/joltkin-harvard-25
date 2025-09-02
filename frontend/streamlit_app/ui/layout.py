# frontend/streamlit_app/ui/layout.py
# SPDX-License-Identifier: Apache-2.0
"""Layout helpers for the Streamlit operator console.

This module centralizes page-level configuration and a small convenience
for building either *stacked* or *side-by-side* layouts based on a
"guided" mode flag.

Rationale
---------
- `configure_page`: Ensure every page sets a consistent browser title and
  uses Streamlit's wide layout. Also renders a prominent in-app title with
  the 🎭🎶 prefix for branding.
- `stack_or_columns_spec`: Many pages share the same content structure but
  need to switch between a step-by-step (stacked) presentation and a compact
  columns layout. This helper abstracts that decision so call sites remain
  concise and consistent.

Conventions
-----------
- Call `configure_page()` exactly once at the beginning of the app startup
  (Streamlit enforces that `st.set_page_config` is called before other UI).
- Use `stack_or_columns_spec` when you want the same code path to support
  both a guided (stacked) flow and a power-user (columns) view.

Example
-------
    from ui.layout import configure_page, stack_or_columns_spec

    configure_page("Joltkin X Algorand — Operator Console")

    guided = st.sidebar.toggle("Guided mode", value=True)
    colA, colB = stack_or_columns_spec([2, 1], guided)
    with colA:
        st.subheader("Primary panel")
    with colB:
        st.subheader("Secondary panel")
"""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st
from streamlit.delta_generator import DeltaGenerator


def configure_page(title: str) -> None:
    """Configure global Streamlit page options and render the main title.

    This sets a consistent browser tab title and enables the *wide* layout
    for better use of horizontal space across the app. It also prints a
    top-level in-app title that includes a branded emoji prefix.

    Args:
      title: Human-readable page title. Used for both the browser tab title
        and the on-page H1 text (with a 🎭🎶 prefix).

    Notes:
      - Streamlit requires `st.set_page_config` to be called before any other
        page elements are created. Ensure this is one of the very first calls
        in your app's entrypoint.
    """
    # Configure Streamlit before rendering any other elements.
    st.set_page_config(page_title=title, layout="wide")
    # Render a consistent, branded H1 at the top of the app.
    st.title(f"🎭🎶 {title}")


def stack_or_columns_spec(
    spec: int | Sequence[float] | Sequence[int],
    guided: bool,
) -> list[DeltaGenerator]:
    """Return a list of layout containers based on *guided* mode.

    In *guided* mode, callers receive a list of vertically stacked containers
    (one per column "slot"); content can then be rendered sequentially for a
    clearer, step-by-step experience.

    In *non-guided* mode, callers receive Streamlit columns arranged according
    to `spec` for a compact, side-by-side layout.

    Args:
      spec: Either an integer (number of equal-width columns) or a sequence
        of numbers expressing relative column widths (e.g., `[2, 1]`).
        This mirrors the accepted input for `st.columns`.
      guided: If True, return stacked containers; if False, return columns.

    Returns:
      A list of `DeltaGenerator` objects. Each item can be used as a context
      manager (i.e., `with cols[i]: ...`) to render content into that region.

    Examples:
      >>> # Guided (stacked) layout with three steps
      >>> c1, c2, c3 = stack_or_columns_spec(3, guided=True)

      >>> # Two columns in a 2:1 ratio when not guided
      >>> left, right = stack_or_columns_spec([2, 1], guided=False)

    Caveats:
      - When `guided=True`, the numeric values in `spec` only determine the
        *count* of containers; the relative widths are ignored because content
        is stacked vertically.
    """
    # Guided: create N independent containers stacked vertically. This keeps
    # the call sites identical (they still "unpack" containers), while making
    # the layout linear and scroll-friendly for stepwise flows.
    if guided:
        count = spec if isinstance(spec, int) else len(spec)
        return [st.container() for _ in range(count)]

    # Non-guided: delegate to Streamlit's native columns implementation, which
    # accepts either an int (equal widths) or a sequence of relative widths.
    # This returns a list[DeltaGenerator] just like the containers above.
    return st.columns(spec)
