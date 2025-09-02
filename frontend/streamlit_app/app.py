# frontend/streamlit_app/app.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

__doc__ = """Joltkin X Algorand — Operator Console (Streamlit).

This module is the Streamlit entrypoint for the operator console. It wires up
the global page chrome, left sidebar (accounts/context), and the main tab set.

Tabs (left-to-right order):
  1) Deploy Router      — Mint ASA + deploy Router app (splits/royalty).
  2) Buy/Resale         — Primary buy and secondary resale atomic flows.
  3) Superfan Pass      — Deploy/opt-in, add points, claim tier, leaderboard.
  4) Harvard Partner    — QR pack generator targeted to Houses/Dorms.
  5) Venue Partner      — QR pack generator for venues; staff screen link.
  6) Tools              — Small helpers (funding, checklists).

Design notes:
* We import sibling packages (ui/, pages/, core/, services/) by adding this
  directory to sys.path. This avoids requiring an installable package layout
  and keeps local imports explicit and stable inside the container.
* Each page module renders its own UI and must ensure stable, unique widget
  keys (see ui/keys.py). Page modules should be side-effect free on import.
* Keep this file intentionally thin. Business logic belongs to services/*
  and Algorand integrations to services/algorand.py.
"""

# ────────────────────── sys.path bootstrap for local packages ─────────────────
# Streamlit executes scripts from the working dir; adding the app directory to
# sys.path allows `from pages import ...` style imports without packaging.
import pathlib
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
# ──────────────────────────────────────────────────────────────────────────────

from typing import Final

import streamlit as st

from pages import (
    deploy_router,
    harvard_partner,
    superfan,
    tools,
    trade,
    venue_partner,
)
from ui.layout import configure_page
from ui.sidebar import render_sidebar_and_status

# ─────────────────────────────── Page chrome ──────────────────────────────────
# Sets the document title and wide layout, and prints a top-level title.
configure_page(title="Joltkin X Algorand — Operator Console")

# Render the sidebar (accounts, guided mode toggle, env hints). The sidebar
# returns a dictionary ("ctx") of useful values (addresses, mnemonics, flags).
# This "ctx" object is passed to each tab renderer to keep state flow explicit.
ctx: dict = render_sidebar_and_status()

# ─────────────────────────────── Tabs wiring ──────────────────────────────────
# Keep tab order stable; Streamlit persists per-tab widget state by key.
TAB_TITLES: Final[list[str]] = [
    "Deploy Router",
    "Buy/Resale",
    "Superfan Pass",
    "Harvard Partner",
    "Venue Partner",
    "Tools",
]

# Note: Unpack into named variables for readability and to keep explicit mapping
# between title and render call. If you add a tab, add its title above and its
# render block below in the matching position.
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(TAB_TITLES)

# Each tab delegates to a page module. Page modules should not mutate global
# Streamlit settings; they may read/write st.session_state as needed.
with tab1:
    deploy_router.render(
        ctx
    )  # Mint ASA → Deploy Router → (opt-ins/prefund handled elsewhere)

with tab2:
    trade.render(ctx)  # Primary buy and resale flows

with tab3:
    superfan.render(ctx)  # Deploy/opt-in, add points, claim tier, leaderboard

with tab4:
    harvard_partner.render(ctx)  # Harvard Houses/Dorms QR pack generator

with tab5:
    venue_partner.render(ctx)  # Venue QR pack + staff screen

with tab6:
    tools.render(ctx)  # Misc helpers (funding, checklists)

# End of file.
