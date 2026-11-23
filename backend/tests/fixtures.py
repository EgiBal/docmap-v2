"""Programmatic tiny fixtures for all formats."""
from __future__ import annotations

from pathlib import Path


def make_docx(p: Path) -> Path:
    import docx

    d = docx.Document()
    d.add_heading("Quarterly Report", 1)
    d.add_paragraph("Revenue grew 12.5% to $4,200,000 in Q3.")
    d.add_paragraph("First point", style="List Bullet")
    d.add_paragraph("Second point", style="List Bullet")
    d.add_heading("Regions", 2)
    t = d.add_table(rows=3, cols=3)
    for i, row in enumerate([["Region", "Q2", "Q3"], ["North", "100", "120"], ["South", "90", "95"]]):
        for j, v in enumerate(row):
            t.cell(i, j).text = v
    d.save(p)
    return p


def make_xlsx(p: Path) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Item", "Qty", "Price", None, None])
    for i in range(1, 21):
        ws.append([f"Widget {i}", i, 9.99 * i, None, None])
    ws.append([None] * 5)
    ws2 = wb.create_sheet("Notes")
    ws2["A1"] = "Total widgets sold: 210"
    wb.save(p)
    return p


def make_pptx(p: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Roadmap 2027"
    s.placeholders[1].text = "Launch beta in March\nShip v1 in June"
    s.notes_slide.notes_text_frame.text = "Speaker note: mention 42 pilot customers"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Budget"
    tb = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(5), Inches(1)).table
    tb.cell(0, 0).text = "Area"; tb.cell(0, 1).text = "Cost"
    tb.cell(1, 0).text = "R&D"; tb.cell(1, 1).text = "1,234,567"
    prs.save(p)
    return p


def make_pdf(p: Path, pages: int = 4) -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    for i in range(1, pages + 1):
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        pdf.cell(0, 8, "ACME Corp Confidential Annual Report", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, f"Section {i}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, f"Net income was {i * 1000 + 234} EUR in section {i}. " * 5)
        pdf.set_y(-20)
        pdf.cell(0, 8, f"Page {i}", align="C")
    pdf.output(str(p))
    return p


def make_scanned_pdf(p: Path) -> Path:
    """Image-only PDF: a rendered picture, no text layer."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (600, 800), "white")
    ImageDraw.Draw(img).text((50, 50), "scanned text here", fill="black")
    ip = p.with_suffix(".png")
    img.save(ip)
    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(ip), x=10, y=10, w=190)
    pdf.output(str(p))
    ip.unlink()
    return p
