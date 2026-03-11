"""
PDF Resume Engine — ATS-safe PDF generation from markdown resume text.

Inspired by anandanair/job-scraper (MIT, pdf_generator.py) — implemented
independently using ReportLab to avoid any license dependency.

ATS-safe rules applied:
  - No tables, no multi-column layouts
  - Standard fonts (Helvetica / Times New Roman)
  - Simple heading hierarchy (H1 → H2 → body)
  - No images or logos
  - Proper Unicode encoding
  - Searchable text (no bitmap rendering)

Usage:
    engine = PDFResumeEngine()
    path = engine.generate(resume_markdown, output_path="resume_google.pdf")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("adapters.pdf_resume_engine")


class PDFResumeEngine:
    """
    Converts a markdown-formatted resume into an ATS-safe PDF.

    Supported markdown elements:
      # H1           → Name/title block (large centered)
      ## H2          → Section headings (bold, underlined)
      ### H3         → Sub-sections (bold)
      **text**       → Bold inline
      - item         → Bullet list
      plain text     → Body paragraph

    Typical workflow:
        1. AI resume customizer (src/ai/resume_customizer.py) produces tailored markdown
        2. PDFResumeEngine converts it to PDF for final delivery
        3. File saved under resume_artifacts/ aligned with job_id
    """

    # A4 dimensions in points
    PAGE_WIDTH = 595.27
    PAGE_HEIGHT = 841.89

    MARGIN_TOP = 50
    MARGIN_BOTTOM = 50
    MARGIN_LEFT = 60
    MARGIN_RIGHT = 60
    LINE_HEIGHT_BODY = 14
    LINE_HEIGHT_H1 = 28
    LINE_HEIGHT_H2 = 20
    LINE_HEIGHT_H3 = 16

    def generate(self, resume_markdown: str, output_path: str | Path) -> Path:
        """
        Generate an ATS-safe PDF from markdown resume text.

        Args:
            resume_markdown: Resume content in simple markdown format.
            output_path: Destination .pdf path (created if needed).

        Returns:
            Path to the created PDF file.
        """
        try:
            from reportlab.lib.pagesizes import A4  # type: ignore
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore
            from reportlab.lib.units import mm  # type: ignore
            from reportlab.platypus import (  # type: ignore
                HRFlowable,
                ListFlowable,
                ListItem,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
            )
        except ImportError:
            logger.error("reportlab not installed. Run: pip install reportlab")
            raise

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=self.MARGIN_RIGHT,
            leftMargin=self.MARGIN_LEFT,
            topMargin=self.MARGIN_TOP,
            bottomMargin=self.MARGIN_BOTTOM,
        )

        styles = self._build_styles()
        story = self._parse_markdown(resume_markdown, styles)

        doc.build(story)
        logger.info("PDF generated: %s", output_path)
        return output_path

    def _build_styles(self) -> dict:
        """Define paragraph styles for ATS-safe rendering."""
        try:
            from reportlab.lib import colors  # type: ignore
            from reportlab.lib.enums import TA_CENTER, TA_LEFT  # type: ignore
            from reportlab.lib.styles import ParagraphStyle  # type: ignore
        except ImportError:
            raise

        return {
            "h1": ParagraphStyle(
                "h1",
                fontName="Helvetica-Bold",
                fontSize=18,
                leading=24,
                alignment=TA_CENTER,
                spaceAfter=6,
                textColor=colors.HexColor("#1a1a2e"),
            ),
            "h2": ParagraphStyle(
                "h2",
                fontName="Helvetica-Bold",
                fontSize=12,
                leading=16,
                spaceBefore=12,
                spaceAfter=4,
                textColor=colors.HexColor("#16213e"),
                borderPadding=(0, 0, 2, 0),
            ),
            "h3": ParagraphStyle(
                "h3",
                fontName="Helvetica-Bold",
                fontSize=10,
                leading=14,
                spaceBefore=6,
                spaceAfter=2,
            ),
            "body": ParagraphStyle(
                "body",
                fontName="Helvetica",
                fontSize=9.5,
                leading=13,
                spaceAfter=2,
                textColor=colors.HexColor("#2d2d2d"),
            ),
            "bullet": ParagraphStyle(
                "bullet",
                fontName="Helvetica",
                fontSize=9.5,
                leading=13,
                leftIndent=12,
                spaceAfter=1,
            ),
        }

    def _parse_markdown(self, md: str, styles: dict) -> list:
        """Parse markdown into ReportLab flowables."""
        try:
            from reportlab.platypus import HRFlowable, Paragraph, Spacer  # type: ignore
        except ImportError:
            raise

        story: list = []
        lines = md.strip().split("\n")
        i = 0
        collected_bullets: list[str] = []

        def flush_bullets() -> None:
            """Flush accumulated bullet items."""
            if not collected_bullets:
                return
            for b in collected_bullets:
                cleaned = self._inline_to_reportlab(b)
                story.append(Paragraph(f"• {cleaned}", styles["bullet"]))
            story.append(Spacer(1, 4))
            collected_bullets.clear()

        while i < len(lines):
            line = lines[i].rstrip()

            if not line:
                flush_bullets()
                story.append(Spacer(1, 4))
                i += 1
                continue

            if line.startswith("### "):
                flush_bullets()
                text = self._inline_to_reportlab(line[4:])
                story.append(Paragraph(text, styles["h3"]))
                i += 1
                continue

            if line.startswith("## "):
                flush_bullets()
                text = self._inline_to_reportlab(line[3:])
                story.append(Paragraph(text, styles["h2"]))
                story.append(
                    HRFlowable(
                        width="100%", thickness=0.5, color="#cccccc", spaceAfter=4
                    )
                )
                i += 1
                continue

            if line.startswith("# "):
                flush_bullets()
                text = self._inline_to_reportlab(line[2:])
                story.append(Paragraph(text, styles["h1"]))
                i += 1
                continue

            if line.startswith("- ") or line.startswith("* "):
                collected_bullets.append(line[2:])
                i += 1
                continue

            # Regular paragraph
            flush_bullets()
            text = self._inline_to_reportlab(line)
            story.append(Paragraph(text, styles["body"]))
            i += 1

        flush_bullets()
        return story

    @staticmethod
    def _inline_to_reportlab(text: str) -> str:
        """Convert inline markdown (**bold**, *italic*) to ReportLab XML tags."""
        # Bold: **text** or __text__
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
        # Italic: *text* or _text_
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
        text = re.sub(r"_(.+?)_", r"<i>\1</i>", text)
        # Escape XML special chars not inside tags
        text = text.replace("&", "&amp;")
        # Re-fix our tags that got double-escaped
        text = text.replace("&amp;lt;", "<").replace("&amp;gt;", ">")
        return text
