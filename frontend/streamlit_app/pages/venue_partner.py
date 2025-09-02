# frontend/streamlit_app/pages/venue_partner.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Streamlit page: Venue Partner — Show Ops

Purpose
-------
Operator workflow to generate venue-facing QR assets and deeplinks for:
  • Mint routes (/mint) with optional "section" segmentation
  • Referral links that attribute scans to a code and Superfan app
  • Venue stamp route (/stamp) that awards Superfan points on scan
  • Poster/sticker PDFs and individual PNG QRs as a ZIP "print pack"

Design notes
------------
• All Streamlit widgets use namespaced keys via `ui.keys.k()` to avoid
  duplicate-element-id collisions across tabs/pages.
• UTM parameters are appended to each deeplink for downstream analytics.
• A small inline gallery previews up to 6 QR codes to sanity-check input.
• PDF generation is optional and depends on `reportlab` + `pillow`.

Security / Safety
-----------------
• This is a **TestNet demo** UX; no persistent secrets are stored here.
• Logo uploads are read to bytes in-memory only; they are not written to disk.
"""

import hashlib
import re
from collections.abc import Iterable

import streamlit as st

from core.config import settings
from services.qrprint import (
    REPORTLAB_OK,
    add_query_params,
    build_full_qr_pack,
    make_qr_png,
)
from ui.keys import k

# ───────────────────────────── helpers ─────────────────────────────


def _slug(x: str) -> str:
    """Return a filesystem-safe token derived from `x`.

    Collapses any non-alphanumeric sequence to a single underscore and trims
    leading/trailing underscores. Intended for filenames within the ZIP.

    Args:
        x: Arbitrary display string (e.g., section, referral code, show code).

    Returns:
        Slugified string containing only [A-Za-z0-9_] characters.
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", x).strip("_")


def _split_csv(s: str) -> list[str]:
    """Parse a simple comma-separated string into a list of trimmed tokens.

    Empty entries are dropped. This avoids surprising blank QR rows.

    Args:
        s: Comma-separated values, potentially with whitespace.

    Returns:
        List of non-empty, trimmed tokens.
    """
    return [part.strip() for part in (s or "").split(",") if part.strip()]


def _preview_grid(entries: Iterable[tuple[str, str, str, str]], utm: dict) -> None:
    """Render a small grid preview of the first few QR codes.

    This is a lightweight smoke test for inputs and UTM composition.
    If QR rendering fails for an entry, we show the deeplink as code.

    Args:
        entries: Iterable of 4-tuples (name, url, caption, group).
        utm: Dict of UTM parameters to append to each url.
    """
    preview = list(entries)[:6]
    if not preview:
        return
    cols = st.columns(min(len(preview), 3))
    for i, (_name, url, caption, _grp) in enumerate(preview):
        with cols[i % len(cols)]:
            try:
                png = make_qr_png(add_query_params(url, utm))
                st.image(png, caption=caption, use_container_width=True)
            except Exception:
                # Render a textual fallback on QR generation failure to keep the UI resilient.
                st.caption(caption)
                st.code(add_query_params(url, utm))


# ───────────────────────────── render ─────────────────────────────


def render(ctx: dict) -> None:
    """Entry point for the Venue Partner tab."""
    st.header("Venue Partner — Show Ops")

    colA, colB = st.columns([2, 1])

    # ============================== Left column ===============================
    with colA:
        st.subheader("QR Pack Generator")

        # --- Inputs (all widget keys are namespaced to avoid collisions) -----
        show_code = st.text_input(
            "Show code",
            value="HORIZON25",
            key=k("venue", "show_code"),
            help="Used in filenames and as the default UTM campaign.",
        )

        sections = st.text_input(
            "Optional sections (comma-separated)",
            value="A,B,C",
            key=k("venue", "sections"),
        )

        ws_points = st.number_input(
            "Venue stamp points",
            min_value=1,
            step=1,
            value=10,
            key=k("venue", "ws_points"),
            help="How many points a scan at the venue stamp station should award.",
        )

        sf_for_qr = st.number_input(
            "Superfan App ID (for stamp & referrals)",
            min_value=0,
            step=1,
            value=int(st.session_state.get("SF_APP_ID", 0)),
            key=k("venue", "sf_for_qr"),
        )

        referral_codes = st.text_input(
            "Referral codes (comma-separated, optional)",
            value="",
            key=k("venue", "ref_codes"),
            help="If set, generates /mint?show=...&ref=<code>&sf=<app> links.",
        )

        # --- UTM parameters used for all links in this pack -------------------
        st.markdown("##### UTM parameters")
        utm_campaign = st.text_input(
            "utm_campaign",
            value=(show_code or "show").lower(),
            key=k("venue", "utm_campaign"),
        )
        utm_source = st.text_input(
            "utm_source",
            value="venue",
            key=k("venue", "utm_source"),
        )
        utm_medium = st.text_input(
            "utm_medium",
            value="qr",
            key=k("venue", "utm_medium"),
        )
        utm_params = {
            "utm_campaign": utm_campaign,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
        }

        # --- Optional poster / sticker PDFs ----------------------------------
        st.markdown("##### Poster & stickers (optional)")
        logo_file = st.file_uploader(
            "Logo for PDFs (PNG/JPG)",
            type=["png", "jpg", "jpeg"],
            key=k("venue", "logo"),
        )
        # Note: Read the uploaded file into memory. We do not persist to disk.
        logo_bytes = logo_file.read() if logo_file else None

        pack_title = st.text_input(
            "Poster title",
            value="Scan • Earn • Enjoy",
            key=k("venue", "poster_title"),
        )
        pack_subtitle = st.text_input(
            "Poster subtitle",
            value="Venue • Harvard Square",
            key=k("venue", "poster_subtitle"),
        )
        opt_posters = st.checkbox(
            "Include posters.pdf",
            value=True,
            key=k("venue", "opt_posters"),
        )
        opt_letter = st.checkbox(
            "Include stickers_letter.pdf (3X5)",
            value=True,
            key=k("venue", "opt_letter"),
        )
        opt_a4 = st.checkbox(
            "Include stickers_a4.pdf (3X8)",
            value=True,
            key=k("venue", "opt_a4"),
        )

        st.markdown("---")

        # --- Generate ZIP: posters/stickers + PNG QRs + MANIFEST.csv ----------
        if st.button(
            "Generate QR Pack (ZIP)",
            use_container_width=True,
            key=k("venue", "gen_zip"),
        ):
            try:
                base = settings.FRONTEND_BASE_URL.rstrip("/")
                entries_raw: list[tuple[str, str, str, str]] = []

                # Mint route (generic)
                entries_raw.append(
                    (
                        f"{show_code}_MINT",
                        f"{base}/mint?show={show_code}",
                        f"{show_code} • Mint",
                        "mint",
                    )
                )

                # Optional "sections" for minting; useful for in-venue seating blocks, etc.
                for s in _split_csv(sections):
                    entries_raw.append(
                        (
                            f"{show_code}_MINT_{_slug(s)}",
                            f"{base}/mint?show={show_code}&section={s}",
                            f"{show_code} • {s}",
                            "mint:section",
                        )
                    )

                # Optional referral links — ties scans to codes and Superfan app
                for r in _split_csv(referral_codes):
                    entries_raw.append(
                        (
                            f"{show_code}_REF_{_slug(r)}",
                            f"{base}/mint?show={show_code}&ref={r}&sf={sf_for_qr}",
                            f"Referral • {r}",
                            "referral",
                        )
                    )

                # Venue stamp deeplink (awards Superfan points)
                entries_raw.append(
                    (
                        f"{show_code}_VENUE_STAMP",
                        f"{base}/stamp?app={sf_for_qr}&show={show_code}&points={ws_points}",
                        f"Venue • {ws_points} pts",
                        "stamp",
                    )
                )

                # Inline preview of a handful of QRs for fast sanity-checking
                _preview_grid(entries_raw, utm_params)

                # Bundle everything into a ZIP. PDFs are included only if reportlab is available.
                data = build_full_qr_pack(
                    entries_raw,
                    pack_title=pack_title,
                    pack_subtitle=pack_subtitle,
                    include_png=True,
                    include_posters=bool(opt_posters and REPORTLAB_OK),
                    include_letter_sheet=bool(opt_letter and REPORTLAB_OK),
                    include_a4_sheet=bool(opt_a4 and REPORTLAB_OK),
                    utm_params=utm_params,
                    logo_png=logo_bytes,
                )

                st.download_button(
                    "Download QR Pack",
                    data=data,
                    file_name=f"{_slug(show_code)}_QR_Pack.zip",
                    mime="application/zip",
                    key=k("venue", "download_zip"),
                )

                if not REPORTLAB_OK:
                    st.warning(
                        "Posters/Sticker sheets skipped: install reportlab & pillow for PDFs."
                    )

                # Quick integrity hint for operators: short SHA-256 prefix
                st.success(f"Ready. SHA-256: {hashlib.sha256(data).hexdigest()[:16]}…")

            except Exception as e:
                # Keep the UI resilient; surface error details for debugging.
                st.error(f"QR Pack failed: {e}")

        # Staff screen deeplink (cycles Mint → Stamp → Leaderboard)
        # Pull Indexer from settings for convenience; can be empty for local-only setups.
        idx_url = getattr(settings, "INDEXER_URL", "")
        staff_url = (
            f"{settings.FRONTEND_BASE_URL}/staff.html"
            f"?show={show_code}"
            f"&app={int(st.session_state.get('SF_APP_ID', 0))}"
            f"&points={int(ws_points)}"
            f"&base={settings.FRONTEND_BASE_URL}"
            f"&idx={idx_url}"
            f"&interval=10"
        )
        st.markdown(
            f"[🔗 Open Staff Screen (new tab)]({staff_url})",
            help="Cycles Mint → Stamp → Leaderboard for on-site screens.",
        )

    # ============================== Right column ==============================
    with colB:
        st.subheader("Leaderboard (points)")
        st.info("Use the Superfan tab to view the live leaderboard (Indexer required).")

        st.divider()
        st.subheader("Deep-link base")
        st.code(settings.FRONTEND_BASE_URL, language="bash")

        st.caption(
            "Tip: Set a public FRONTEND_BASE_URL before printing posters for off-site deployments."
        )
