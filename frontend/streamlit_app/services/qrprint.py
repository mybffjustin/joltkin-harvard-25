# frontend/streamlit_app/services/qrprint.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
QR image and print-pack generation utilities.

This module provides:
  • High-quality PNG QR generation (via qrcode[pil])
  • Turn-key ZIP "print packs" containing:
      - posters.pdf (1 QR per page, letter/A4)
      - stickers_letter.pdf (3X5 grid)
      - stickers_a4.pdf     (3X8 grid)
      - qrs/*.png           (individual PNGs)
      - MANIFEST.csv        (filenames, links, captions, groups, UTM fields)

Design goals
------------
- **Optional heavy deps:** gracefully degrade if ReportLab/Pillow are missing
  (we still produce PNGs and a README note in the ZIP).
- **Deterministic output:** filenames sanitized; consistent layouts.
- **Operator-friendly:** sensible defaults; small helpers to compose packs.

All paths/bytes are in-memory; the caller is responsible for writing to disk.
"""

import csv
import io
import re
import zipfile

# --- Optional dependencies ----------------------------------------------------

try:
    import qrcode  # type: ignore
except ImportError:  # pragma: no cover - exercised at runtime if qrcode not installed
    qrcode = None  # Allows PNG generation to be feature-detected at call sites.

try:
    # ReportLab + Pillow for PDF output
    from PIL import Image  # type: ignore
    from reportlab.lib.pagesizes import A4, letter  # type: ignore
    from reportlab.lib.units import inch  # type: ignore
    from reportlab.lib.utils import ImageReader  # type: ignore
    from reportlab.pdfgen import canvas as _pdf_canvas  # type: ignore

    REPORTLAB_OK = True
except Exception:  # pragma: no cover - environment dependent
    REPORTLAB_OK = False


# =============================================================================
# Small helpers
# =============================================================================


def sanitize_name(s: str) -> str:
    """Convert a label to a filesystem-safe base name.

    - Collapse whitespace to underscores.
    - Keep only alnum, underscore, and hyphen.
    - Fallback to "QR" if the result is empty.

    Args:
      s: Arbitrary label.

    Returns:
      Sanitized filename stem.
    """
    s = re.sub(r"\s+", "_", (s or "").strip())
    s = re.sub(r"[^A-Za-z0-9_\-]", "", s)
    return s or "QR"


def make_qr_png(data: str, box_size: int = 12, border: int = 2) -> bytes:
    """Generate a PNG QR code for `data`.

    Uses medium error correction (M) to balance density and scannability.

    Args:
      data: Encoded contents (URL or text).
      box_size: Pixel size of one QR module (default 12 → large, print-friendly).
      border: Quiet-zone border modules (default 2).

    Returns:
      PNG bytes.

    Raises:
      RuntimeError: if `qrcode[pil]` is not installed.
    """
    if not qrcode:
        raise RuntimeError(
            "Missing dependency: qrcode[pil]. Install: pip install qrcode[pil]"
        )

    qr = qrcode.QRCode(
        version=None,  # Let the library choose minimal fitting version.
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    # Render as RGB (opaque white background for better print results).
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def add_query_params(url: str, params: dict[str, str]) -> str:
    """Append non-empty query params to a URL (no escaping beyond '=' & '&').

    This is a lightweight alternative used for *pre-escaped* or simple values.
    Prefer urllib.parse.urlencode if values may contain special characters.

    Args:
      url: Base URL (with or without a '?').
      params: Map of key → value (falsy values are skipped).

    Returns:
      URL with appended parameters.
    """
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    parts = [f"{k}={v}" for k, v in params.items() if v]
    return url + (sep + "&".join(parts) if parts else "")


# =============================================================================
# PDF makers (posters & sticker sheets)
# =============================================================================


def _poster_pdf(
    entries: list[tuple[str, str, str]],
    pack_title: str,
    pack_subtitle: str,
    logo_png: bytes | None = None,
) -> bytes:
    """Render a poster per entry (US Letter), each with one large QR and caption.

    Args:
      entries: List of (name, url, caption).
      pack_title: Title printed at the top of every page.
      pack_subtitle: Subtitle printed beneath the title.
      logo_png: Optional small logo shown on each page (top-right).

    Returns:
      PDF bytes.

    Raises:
      RuntimeError: if ReportLab/Pillow are not available.
    """
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab not installed")

    bio = io.BytesIO()
    cpdf = _pdf_canvas(bio, pagesize=letter)
    width, height = letter

    # Prepare logo (if any). Errors are non-fatal (logo becomes None).
    logo_reader = None
    if logo_png:
        try:
            logo_reader = ImageReader(Image.open(io.BytesIO(logo_png)))
        except Exception:
            logo_reader = None  # Keep going without a logo.

    for _name, url, caption in entries:
        # Title & subtitle
        cpdf.setFillColorRGB(0, 0, 0)
        cpdf.setFont("Helvetica-Bold", 22)
        cpdf.drawCentredString(width / 2, height - 72, pack_title)
        cpdf.setFont("Helvetica", 12)
        cpdf.drawCentredString(width / 2, height - 96, pack_subtitle)

        # Logo (top-right)
        if logo_reader:
            try:
                cpdf.drawImage(
                    logo_reader, width - 115, height - 115, 86, 86, mask="auto"
                )
            except Exception:
                pass  # Ignore bad logo bytes.

        # QR (large, centered)
        png = make_qr_png(url, box_size=14, border=2)
        img = Image.open(io.BytesIO(png))
        side = 4.8 * inch  # Visual size of QR on the page
        x = (width - side) / 2
        y = (height - side) / 2
        cpdf.drawImage(ImageReader(img), x, y, side, side, mask="auto")

        # Caption under QR, URL footer
        cpdf.setFont("Helvetica-Bold", 16)
        cpdf.drawCentredString(width / 2, y - 0.4 * inch, caption[:64])
        cpdf.setFont("Helvetica", 10)
        cpdf.drawCentredString(width / 2, 0.8 * inch, url[:95])

        cpdf.showPage()

    cpdf.save()
    return bio.getvalue()


def _sticker_grid_pdf(
    entries: list[tuple[str, str, str]],
    page_size: str = "letter",
    logo_png: bytes | None = None,
) -> bytes:
    """Render compact sticker sheets (grid of QR labels) for letter or A4.

    Layouts:
      - letter: 3 columns X 5 rows, generous QR size for 1.8" squares
      - A4:     3 columns X 8 rows, slightly smaller QR to fit page

    Args:
      entries: List of (name, url, caption).
      page_size: "letter" or "a4" (case-insensitive).
      logo_png: Optional small logo drawn once per page (top-right).

    Returns:
      PDF bytes.

    Raises:
      RuntimeError: if ReportLab/Pillow are not available.
    """
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab not installed")

    if page_size.lower() == "letter":
        pagesize = letter
        cols, rows = 3, 5
        margin, gutter = 36, 18  # points
        side = 1.8 * 72  # ~1.8 inches QR side
    else:
        pagesize = A4
        cols, rows = 3, 8
        margin, gutter = 36, 16
        side = 1.55 * 72

    width, height = pagesize
    cell_w = (width - 2 * margin - (cols - 1) * gutter) / cols
    cell_h = (height - 2 * margin - (rows - 1) * gutter) / rows

    bio = io.BytesIO()
    cpdf = _pdf_canvas(bio, pagesize=pagesize)

    # Optional logo preparation.
    logo_reader = None
    if logo_png:
        try:
            logo_reader = ImageReader(Image.open(io.BytesIO(logo_png)))
        except Exception:
            logo_reader = None

    def draw_cell(ix: int, iy: int, _name: str, url: str, caption: str) -> None:
        """Draw a single grid cell (QR + caption) at column ix, row iy."""
        x0 = margin + ix * (cell_w + gutter)
        y0 = height - margin - (iy + 1) * cell_h - iy * gutter

        png = make_qr_png(url, box_size=10, border=2)
        img = Image.open(io.BytesIO(png))

        qx = x0 + (cell_w - side) / 2
        qy = y0 + (cell_h - side) / 2 + 14  # Slight vertical bias for label space
        cpdf.drawImage(ImageReader(img), qx, qy, side, side, mask="auto")

        cpdf.setFont("Helvetica", 8)
        cpdf.drawCentredString(x0 + cell_w / 2, y0 + 12, caption[:40])

    i = 0
    for name, url, caption in entries:
        # Stamp logo at the first page's corner (non-fatal if it fails).
        if i % (cols * rows) == 0 and logo_reader:
            try:
                cpdf.drawImage(
                    logo_reader, width - 100, height - 100, 72, 72, mask="auto"
                )
            except Exception:
                pass

        col = i % cols
        row = (i // cols) % rows
        draw_cell(col, row, name, url, caption)
        i += 1

        # Advance to next page when the current grid is filled.
        if i % (cols * rows) == 0:
            cpdf.showPage()

    # If the last page is partially filled, finalize it.
    if i % (cols * rows) != 0:
        cpdf.showPage()

    cpdf.save()
    return bio.getvalue()


def _manifest_csv(
    entries: list[tuple[str, str, str, str]], utm: dict[str, str]
) -> bytes:
    """Create a CSV manifest for the pack.

    Columns:
      filename, url, caption, group, utm_source, utm_medium, utm_campaign
    """
    bio = io.StringIO()
    w = csv.writer(bio)
    w.writerow(
        [
            "filename",
            "url",
            "caption",
            "group",
            "utm_source",
            "utm_medium",
            "utm_campaign",
        ]
    )
    for fn, url, cap, grp in entries:
        w.writerow(
            [
                fn,
                url,
                cap,
                grp,
                utm.get("utm_source", ""),
                utm.get("utm_medium", ""),
                utm.get("utm_campaign", ""),
            ]
        )
    return bio.getvalue().encode("utf-8")


# =============================================================================
# ZIP print pack builder
# =============================================================================


def build_full_qr_pack(
    entries_raw: list[tuple[str, str, str, str]],
    *,
    pack_title: str,
    pack_subtitle: str,
    include_png: bool = True,
    include_posters: bool = True,
    include_letter_sheet: bool = True,
    include_a4_sheet: bool = True,
    utm_params: dict[str, str] | None = None,
    logo_png: bytes | None = None,
) -> bytes:
    """Bundle a complete QR "print pack" ZIP.

    Args:
      entries_raw: List of (name, url, caption, group).
      pack_title: Title for poster/sticker PDFs.
      pack_subtitle: Subtitle for poster PDF.
      include_png: If True, includes qrs/*.png files.
      include_posters: If True, includes posters.pdf (ReportLab required).
      include_letter_sheet: If True, includes stickers_letter.pdf (ReportLab).
      include_a4_sheet: If True, includes stickers_a4.pdf (ReportLab).
      utm_params: Optional UTM dict added to every URL (utm_* keys, non-empty).
      logo_png: Optional logo bytes for PDFs.

    Returns:
      A ZIP file (as bytes) containing all requested artifacts.

    Notes:
      - If ReportLab is missing, PDFs are skipped and a NO_PDF_NOTE.txt is added.
      - Filenames are sanitized to ensure OS compatibility.
    """
    utm = utm_params or {}

    # Normalize entries and add UTM params using a safe encoder.
    from urllib.parse import urlencode

    entries: list[tuple[str, str, str, str]] = []
    for name, url, cap, grp in entries_raw:
        qp = urlencode({k: v for k, v in utm.items() if v})
        url2 = url + (("&" if "?" in url else "?") + qp if qp else "")
        entries.append((sanitize_name(name), url2, cap, grp))

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        # Manifest is always present.
        z.writestr("MANIFEST.csv", _manifest_csv(entries, utm))

        # Individual PNGs.
        if include_png:
            for name, url, _cap, _grp in entries:
                z.writestr(f"qrs/{name}.png", make_qr_png(url, box_size=12, border=2))

        # PDFs (if ReportLab available).
        if include_posters and REPORTLAB_OK:
            poster = _poster_pdf(
                [(n, u, c) for n, u, c, _ in entries],
                pack_title,
                pack_subtitle,
                logo_png,
            )
            z.writestr("posters.pdf", poster)

        if REPORTLAB_OK:
            if include_letter_sheet:
                z.writestr(
                    "stickers_letter.pdf",
                    _sticker_grid_pdf(
                        [(n, u, c) for n, u, c, _ in entries],
                        page_size="letter",
                        logo_png=logo_png,
                    ),
                )
            if include_a4_sheet:
                z.writestr(
                    "stickers_a4.pdf",
                    _sticker_grid_pdf(
                        [(n, u, c) for n, u, c, _ in entries],
                        page_size="a4",
                        logo_png=logo_png,
                    ),
                )
        else:
            # Provide a friendly note in lieu of PDFs.
            z.writestr(
                "NO_PDF_NOTE.txt",
                "PDF generation skipped.\nInstall: pip install reportlab pillow\n",
            )

    return bio.getvalue()
