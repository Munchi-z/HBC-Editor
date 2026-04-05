# reports/pdf_builder.py
# HBCE — Hybrid Controls Editor
# Professional PDF Report Builder — V0.1.9a-alpha
#
# Uses ReportLab (already in requirements.txt).
# Produces landscape A4 PDFs with:
#   - Branded header  (HBCE logo text + report title + timestamp)
#   - Styled data table with alternating row stripes
#   - Per-report-type column widths and color coding
#     (alarm priority colours, trend value highlighting)
#   - Page-number footer  ("Page N of M")
#   - Summary statistics box below the table
#
# Usage:
#   builder = HBCEPDFBuilder("alarm_history", headers, rows, "/path/out.pdf")
#   builder.build(device_name="FEC2611-0", params={"date_from": "…"})

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from core.logger import get_logger

logger = get_logger(__name__)

# ── Alarm priority colours (BACnet standard 1-8) ─────────────────────────────
_PRIORITY_COLORS = {
    "1": "#7B0000",   # Life Safety — deep red
    "2": "#B71C1C",   # Critical equipment
    "3": "#E53935",   # Fire
    "4": "#FB8C00",   # General alarm
    "5": "#F9A825",   # Supervisory
    "6": "#558B2F",   # Operational
    "7": "#1565C0",   # Diagnostic
    "8": "#37474F",   # Informational
}

# Column width hints per report type (fractions; will be scaled to page width)
_COL_FRACTIONS = {
    "point_snapshot":  [2.5, 1.2, 0.8, 1.0, 0.8, 1.0, 1.5],
    "alarm_history":   [0.6, 1.6, 1.5, 1.2, 2.5, 0.7, 1.2, 1.2],
    "trend_data":      [2.0, 2.0, 1.0, 1.5],
    "backup_log":      [0.6, 1.6, 1.5, 2.5, 1.0, 0.8, 1.0, 1.0],
    "schedule_summary":[1.5, 2.0, 0.8, 0.8, 0.8, 1.2, 1.5],
}

# Which column contains the priority value (0-based) for alarm reports
_PRIORITY_COL = {"alarm_history": 5}


class HBCEPDFBuilder:
    """
    Builds a professional landscape-A4 PDF report.

    Parameters
    ----------
    report_type : str
        One of: point_snapshot | alarm_history | trend_data |
                backup_log | schedule_summary
    headers : list[str]
        Column header strings.
    rows : list[list]
        Data rows (each a list of str/int/float).
    output_path : str
        Destination .pdf file path.
    """

    APP_NAME    = "HBCE — Hybrid Controls Editor"
    ACCENT_HEX  = "#2B6CB0"   # header / title colour
    STRIPE_EVEN = "#F2F4F8"
    STRIPE_ODD  = "#FFFFFF"
    BORDER_HEX  = "#C8D0DC"
    TEXT_DARK   = "#1A202C"
    TEXT_MID    = "#4A5568"

    def __init__(self, report_type: str, headers: List[str],
                 rows: List[list], output_path: str):
        self.report_type = report_type
        self.headers     = headers
        self.rows        = rows
        self.output_path = output_path

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self, report_title: str = "",
              device_name: str = "",
              params: Optional[dict] = None) -> str:
        """
        Generate the PDF and return the output path.
        Raises RuntimeError if reportlab is not installed.
        """
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm, mm
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle,
                Paragraph, Spacer, KeepTogether,
            )
            from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

        except ImportError as e:
            raise RuntimeError(
                "reportlab is not installed. Run: pip install reportlab"
            ) from e

        page_size   = landscape(A4)
        page_w, page_h = page_size
        margin       = 1.5 * cm
        usable_w     = page_w - 2 * margin

        # ── Styles ────────────────────────────────────────────────────────────
        styles  = getSampleStyleSheet()
        accent  = colors.HexColor(self.ACCENT_HEX)
        dark    = colors.HexColor(self.TEXT_DARK)
        mid     = colors.HexColor(self.TEXT_MID)

        style_app = ParagraphStyle(
            "AppName", parent=styles["Normal"],
            fontSize=9, textColor=mid, leading=11,
        )
        style_title = ParagraphStyle(
            "ReportTitle", parent=styles["Normal"],
            fontSize=14, textColor=accent, leading=17,
            fontName="Helvetica-Bold",
        )
        style_meta = ParagraphStyle(
            "Meta", parent=styles["Normal"],
            fontSize=8, textColor=mid, leading=10,
        )
        style_summary = ParagraphStyle(
            "Summary", parent=styles["Normal"],
            fontSize=8, textColor=dark, leading=11,
        )

        # ── Document ──────────────────────────────────────────────────────────
        doc = SimpleDocTemplate(
            self.output_path,
            pagesize=page_size,
            leftMargin=margin, rightMargin=margin,
            topMargin=margin,  bottomMargin=1.8 * cm,
            title=report_title or "HBCE Report",
            author=self.APP_NAME,
        )

        story: list = []

        # ── Header block ──────────────────────────────────────────────────────
        title_text = report_title or self.report_type.replace("_", " ").title()
        ts_text    = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        dev_text   = f"Device: {device_name}" if device_name else ""

        header_data = [[
            Paragraph(f"<b>{self.APP_NAME}</b>", style_app),
            Paragraph(title_text, style_title),
            Paragraph(f"{ts_text}<br/>{dev_text}", style_meta),
        ]]
        header_tbl = Table(
            header_data,
            colWidths=[usable_w * 0.30, usable_w * 0.42, usable_w * 0.28],
        )
        header_tbl.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW",    (0, 0), (-1, -1), 1.0, accent),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("ALIGN",        (2, 0), (2, 0),   "RIGHT"),
        ]))
        story.append(header_tbl)
        story.append(Spacer(1, 0.35 * cm))

        # ── Param summary (if any) ────────────────────────────────────────────
        if params:
            param_parts = []
            for k, v in params.items():
                if v:
                    label = k.replace("_", " ").title()
                    param_parts.append(f"<b>{label}:</b> {v}")
            if param_parts:
                story.append(Paragraph("  ·  ".join(param_parts), style_meta))
                story.append(Spacer(1, 0.25 * cm))

        # ── Data table ────────────────────────────────────────────────────────
        if self.rows:
            story.append(self._build_table(
                usable_w, colors, accent,
                TA_LEFT, TA_CENTER,
            ))
        else:
            story.append(Paragraph(
                "<i>No data available for the selected parameters.</i>",
                style_meta,
            ))

        story.append(Spacer(1, 0.4 * cm))

        # ── Summary statistics ────────────────────────────────────────────────
        summary = self._build_summary()
        if summary:
            story.append(Paragraph(summary, style_summary))

        # ── Build with page-number callback ───────────────────────────────────
        def _add_footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor(self.TEXT_MID))
            footer_y = 0.8 * cm
            canvas.drawString(margin, footer_y, self.APP_NAME)
            page_text = f"Page {doc.page}"
            canvas.drawRightString(page_w - margin, footer_y, page_text)
            canvas.restoreState()

        doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
        logger.info(f"PDF report written: {self.output_path}  "
                    f"({len(self.rows)} rows)")
        return self.output_path

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _col_widths(self, usable_w: float) -> List[float]:
        fracs = _COL_FRACTIONS.get(self.report_type)
        n = len(self.headers)
        if fracs and len(fracs) == n:
            total = sum(fracs)
            return [usable_w * f / total for f in fracs]
        # Equal widths fallback
        return [usable_w / n] * n

    def _build_table(self, usable_w, colors_mod, accent,
                     ta_left, ta_center):
        from reportlab.platypus import Table, TableStyle

        col_widths = self._col_widths(usable_w)
        priority_col = _PRIORITY_COL.get(self.report_type, -1)

        # Build data
        data = [self.headers]
        for row in self.rows:
            data.append([str(v) if v is not None else "" for v in row])

        tbl = Table(data, colWidths=col_widths, repeatRows=1)

        # Base style
        base_cmds = [
            # Header
            ("BACKGROUND",    (0, 0), (-1, 0),  accent),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors_mod.white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0),  8),
            ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
            ("VALIGN",        (0, 0), (-1, 0),  "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, 0),  4),
            ("TOPPADDING",    (0, 0), (-1, 0),  4),
            # Data rows
            ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",      (0, 1), (-1, -1), 7),
            ("VALIGN",        (0, 1), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 1), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            # Grid
            ("GRID",          (0, 0), (-1, -1), 0.3,
             colors_mod.HexColor(self.BORDER_HEX)),
        ]

        # Alternating stripes
        for row_idx in range(1, len(data)):
            bg = (colors_mod.HexColor(self.STRIPE_EVEN)
                  if row_idx % 2 == 0
                  else colors_mod.HexColor(self.STRIPE_ODD))
            base_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))

        # Priority colour coding for alarm reports
        if priority_col >= 0:
            for row_idx, row in enumerate(self.rows, start=1):
                if len(row) > priority_col:
                    pri = str(row[priority_col])
                    hex_col = _PRIORITY_COLORS.get(pri)
                    if hex_col:
                        pri_color = colors_mod.HexColor(hex_col)
                        base_cmds += [
                            ("BACKGROUND", (priority_col, row_idx),
                             (priority_col, row_idx), pri_color),
                            ("TEXTCOLOR",  (priority_col, row_idx),
                             (priority_col, row_idx), colors_mod.white),
                            ("FONTNAME",   (priority_col, row_idx),
                             (priority_col, row_idx), "Helvetica-Bold"),
                        ]

        tbl.setStyle(TableStyle(base_cmds))
        return tbl

    def _build_summary(self) -> str:
        n = len(self.rows)
        if n == 0:
            return ""

        rt = self.report_type
        if rt == "alarm_history":
            active  = sum(1 for r in self.rows
                         if len(r) > 6 and "active" in str(r[6]).lower())
            acked   = sum(1 for r in self.rows
                         if len(r) > 6 and "acked" in str(r[6]).lower())
            return (f"<b>Summary:</b>  Total alarms: {n}  ·  "
                    f"Active: {active}  ·  Acknowledged: {acked}  ·  "
                    f"Cleared: {n - active - acked}")

        if rt == "point_snapshot":
            return f"<b>Summary:</b>  Total points: {n}"

        if rt == "trend_data":
            try:
                vals = [float(r[2]) for r in self.rows if len(r) > 2 and r[2]]
                if vals:
                    return (f"<b>Summary:</b>  Samples: {n}  ·  "
                            f"Min: {min(vals):.2f}  ·  "
                            f"Max: {max(vals):.2f}  ·  "
                            f"Avg: {sum(vals)/len(vals):.2f}")
            except (ValueError, IndexError):
                pass

        if rt == "backup_log":
            complete = sum(1 for r in self.rows
                          if len(r) > 6 and r[6] == "complete")
            return (f"<b>Summary:</b>  Total backups: {n}  ·  "
                    f"Complete: {complete}  ·  Failed: {n - complete}")

        if rt == "schedule_summary":
            return f"<b>Summary:</b>  Total schedule blocks: {n}"

        return f"<b>Summary:</b>  Total rows: {n}"
