# frontend/streamlit_app/pages/harvard_partner.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Streamlit page: Harvard Partner — Show Ops

Purpose
-------
Operator-facing tooling to generate printable and on-screen QR assets for
Harvard-affiliated campaigns (e.g., student org fairs, house/dorm outreach).
Outputs a ZIP that can include:
  • PNG QR images for quick sharing
  • posters.pdf (one large QR per page, optional logo)
  • stickers_letter.pdf (3X5 grid) and stickers_a4.pdf (3X8 grid)
  • MANIFEST.csv with UTM parameters for campaign attribution

Design
------
- **Deterministic filenames** via `_slug()` for cross-platform safety.
- **Small inline preview** of a few QRs so operators can visually verify links.
- **UTM parameters** applied uniformly to every generated URL.
- Uses unique widget keys via `ui.keys.k()` to avoid Streamlit element-ID
  collisions across tabs/pages.

Security & Privacy
------------------
- This page does not handle secrets/keys. It only composes URLs and renders
  images from local QR generation. Deep-link base comes from configuration.

Dependencies
------------
- `services.qrprint`: encapsulates QR generation and PDF composition.
- `core.constants`: provides Harvard house/dorm lists for convenience.
"""

import hashlib
import re
from collections.abc import Iterable

import streamlit as st

from core.config import settings
from core.constants import FIRST_YEAR_DORMS, HARVARD_HOUSES
from services.qrprint import (
    REPORTLAB_OK,
    add_query_params,
    build_full_qr_pack,
    make_qr_png,
)
from ui.keys import k


def _slug(x: str) -> str:
    """Return a filesystem- and URL-safe slug.

    This is used for filenames in the QR ZIP (e.g., posters, PNG names).
    It preserves alphanumeric characters and collapses all other runs into a
    single underscore. Leading/trailing underscores are stripped.

    Args:
        x: Arbitrary user-provided string (e.g., "Adams House A")

    Returns:
        A slugified identifier, e.g. "Adams_House_A".
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", x).strip("_")


def _split_csv(s: str) -> list[str]:
    """Split a comma-separated string into trimmed, non-empty tokens.

    Streamlit inputs frequently use comma-separated free text. This helper
    normalizes empty/whitespace entries out of the list.

    Args:
        s: Comma-separated values (may be None/empty).

    Returns:
        List of non-empty, trimmed strings.
    """
    return [part.strip() for part in (s or "").split(",") if part.strip()]


def _preview_grid(entries: Iterable[tuple[str, str, str, str]], utm: dict) -> None:
    """Render a compact preview grid of the first few QR codes.

    Previewing a handful of codes allows operators to validate the
    deep-link formatting and UTM application before downloading the full ZIP.

    Args:
        entries: Iterable of 4-tuples `(name, url, caption, group)`.
        utm: Dict of UTM parameters to be applied to each preview URL.
    """
    preview = list(entries)[:6]
    if not preview:
        return

    # Use up to 3 columns for a clean preview layout.
    cols = st.columns(min(len(preview), 3))
    for i, (_name, url, caption, _grp) in enumerate(preview):
        with cols[i % len(cols)]:
            try:
                # Generate a small QR for the UTM-enriched URL.
                png = make_qr_png(add_query_params(url, utm))
                st.image(png, caption=caption, use_container_width=True)
            except Exception:
                # If QR rendering fails for any reason, fall back to showing the URL.
                st.caption(caption)
                st.code(add_query_params(url, utm))


def render(ctx: dict) -> None:
    """Render the Harvard Partner page.

    This page focuses on **print** and **scan** flows for campus activations:
      - Generates house/dorm-specific mint links
      - Supports referral codes bound to a Superfan app id
      - Produces posters/sticker sheets if PDF tooling is present

    Args:
        ctx: Sidebar-provided context. Not heavily used on this page, but
             included for future parity with other tabs.
    """
    st.header("Harvard Partner — Show Ops")

    left, right = st.columns([2, 1])

    # ──────────────────────────────────────────────────────────────────────
    # Left column: Campaign configuration, target audiences, and ZIP build
    # ──────────────────────────────────────────────────────────────────────
    with left:
        # Inputs — basic campaign identity & scoping
        show_code = st.text_input(
            "Show code",
            value="HORIZON25",
            key=k("harvard", "show_code"),
            help="Used in filenames and UTM campaign.",
        )

        sections = st.text_input(
            "Sections (comma-separated)",
            value="A,B,C",
            key=k("harvard", "sections"),
        )

        # Superfan app id is used for stamp/referral attribution in the public app.
        sf_for_qr = st.number_input(
            "Superfan App ID (for stamp/referrals)",
            min_value=0,
            step=1,
            value=int(st.session_state.get("SF_APP_ID", 0)),
            key=k("harvard", "sf_app_id"),
        )

        referral_codes = st.text_input(
            "Referral codes (comma-separated)",
            value="alice,bob,charlie",
            key=k("harvard", "ref_codes"),
            help="Generates /mint?show=...&ref=<code>&sf=<app> deep links.",
        )

        # Target audiences — predefined Harvard lists for convenience
        st.markdown("##### Target audiences")
        include_houses = st.checkbox(
            "Include House Mint QRs",
            value=True,
            key=k("harvard", "inc_houses"),
        )
        include_dorms = st.checkbox(
            "Include Dorm Mint QRs",
            value=True,
            key=k("harvard", "inc_dorms"),
        )
        houses_selected = st.multiselect(
            "Houses",
            HARVARD_HOUSES,
            default=HARVARD_HOUSES,
            key=k("harvard", "houses"),
        )
        dorms_selected = st.multiselect(
            "First-Year Dorms",
            FIRST_YEAR_DORMS,
            default=FIRST_YEAR_DORMS,
            key=k("harvard", "dorms"),
        )

        # UTM parameters — applied uniformly to *every* generated URL
        st.markdown("##### UTM parameters")
        utm_campaign = st.text_input(
            "utm_campaign",
            value=(show_code or "show").lower(),
            key=k("harvard", "utm_campaign"),
        )
        utm_source = st.text_input(
            "utm_source",
            value="student_org_fair",
            key=k("harvard", "utm_source"),
        )
        utm_medium = st.text_input(
            "utm_medium",
            value="qr",
            key=k("harvard", "utm_medium"),
        )
        utm_params = {
            "utm_campaign": utm_campaign,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
        }

        # Optional branding and PDF toggles
        st.markdown("##### Poster & stickers (optional)")
        logo_file = st.file_uploader(
            "Logo for PDFs (PNG/JPG)",
            type=["png", "jpg", "jpeg"],
            key=k("harvard", "logo"),
        )
        logo_bytes = logo_file.read() if logo_file else None

        pack_title = st.text_input(
            "Poster title",
            value="Mint • Stamp • Win Perks",
            key=k("harvard", "poster_title"),
        )
        pack_sub = st.text_input(
            "Poster subtitle",
            value="Scan the QR below",
            key=k("harvard", "poster_sub"),
        )
        opt_posters = st.checkbox(
            "Include posters.pdf",
            value=True,
            key=k("harvard", "opt_posters"),
        )
        opt_letter = st.checkbox(
            "Include stickers_letter.pdf (3X5)",
            value=True,
            key=k("harvard", "opt_letter"),
        )
        opt_a4 = st.checkbox(
            "Include stickers_a4.pdf (3X8)",
            value=True,
            key=k("harvard", "opt_a4"),
        )

        st.markdown("---")

        # Primary action — build the print pack ZIP
        if st.button(
            "Generate PRINT PACK (ZIP)",
            use_container_width=True,
            key=k("harvard", "gen_zip"),
        ):
            try:
                base = settings.FRONTEND_BASE_URL.rstrip("/")
                entries_raw: list[tuple[str, str, str, str]] = []

                # 1) Generic mint link + per-section links
                entries_raw.append(
                    (
                        f"{show_code}_MINT",
                        f"{base}/mint?show={show_code}",
                        f"{show_code} • Mint",
                        "mint",
                    )
                )
                for sec in _split_csv(sections):
                    entries_raw.append(
                        (
                            f"{show_code}_MINT_{_slug(sec)}",
                            f"{base}/mint?show={show_code}&section={sec}",
                            f"{show_code} • {sec}",
                            "mint:section",
                        )
                    )

                # 2) Per-house and per-dorm mint links
                if include_houses:
                    for h in houses_selected:
                        entries_raw.append(
                            (
                                f"{show_code}_MINT_{_slug(h)}",
                                f"{base}/mint?show={show_code}&house={h}",
                                f"{show_code} • {h}",
                                "mint:house",
                            )
                        )
                if include_dorms:
                    for d in dorms_selected:
                        entries_raw.append(
                            (
                                f"{show_code}_MINT_{_slug(d)}",
                                f"{base}/mint?show={show_code}&dorm={d}",
                                f"{show_code} • {d}",
                                "mint:dorm",
                            )
                        )

                # 3) Referral codes — bound to Superfan app id for attribution
                for r in _split_csv(referral_codes):
                    entries_raw.append(
                        (
                            f"{show_code}_REF_{_slug(r)}",
                            f"{base}/mint?show={show_code}&ref={r}&sf={sf_for_qr}",
                            f"Referral • {r}",
                            "referral",
                        )
                    )

                # Show a small inline preview for sanity check
                _preview_grid(entries_raw, utm_params)

                # Build ZIP; PDFs included only if reportlab/pillow are available.
                data = build_full_qr_pack(
                    entries_raw,
                    pack_title=pack_title,
                    pack_subtitle=pack_sub,
                    include_png=True,
                    include_posters=bool(opt_posters and REPORTLAB_OK),
                    include_letter_sheet=bool(opt_letter and REPORTLAB_OK),
                    include_a4_sheet=bool(opt_a4 and REPORTLAB_OK),
                    utm_params=utm_params,
                    logo_png=logo_bytes,
                )

                # Download
                st.download_button(
                    "Download PRINT PACK",
                    data=data,
                    file_name=f"{_slug(show_code)}_PrintPack.zip",
                    mime="application/zip",
                    key=k("harvard", "download_zip"),
                )
                st.success(f"Ready. SHA-256: {hashlib.sha256(data).hexdigest()[:16]}…")

                # Helpful nudge if PDF deps are missing
                if not REPORTLAB_OK:
                    st.warning(
                        "Posters/Sticker sheets skipped: install reportlab & pillow for PDFs."
                    )

            except Exception as e:
                # Surface a concise, user-actionable error
                st.error(f"QR Pack failed: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # Right column: Deep-link base visibility and Staff Screen quick link
    # ──────────────────────────────────────────────────────────────────────
    with right:
        st.subheader("Deep-link base")
        st.code(settings.FRONTEND_BASE_URL, language="bash")

        st.subheader("Staff Screen")
        idx_url = getattr(settings, "INDEXER_URL", "")
        ws_points_default = (
            10  # Points increment used by stamp flows on the staff screen
        )

        # Staff screen cycles through Mint → Stamp → Leaderboard and relies on
        # Superfan app id for points attribution. Keep params explicit so operators
        # can copy and share easily.
        staff_url = (
            f"{settings.FRONTEND_BASE_URL}/staff.html"
            f"?show={show_code}"
            f"&app={int(st.session_state.get('SF_APP_ID', 0))}"
            f"&points={ws_points_default}"
            f"&base={settings.FRONTEND_BASE_URL}"
            f"&idx={idx_url}"
            f"&interval=10"
        )
        st.markdown(
            f"[🔗 Open Staff Screen (new tab)]({staff_url})",
            help="Cycles Mint → Stamp → Leaderboard; pass app id for Superfan points.",
        )

        st.divider()
        st.caption(
            "Tip: Set a public FRONTEND_BASE_URL before printing posters for campus events."
        )
