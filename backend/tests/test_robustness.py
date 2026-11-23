"""T14 robustness tests for the conversion layer. Fixtures are built in tmp_path at test time."""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import glob
import io
import os
import random
import re
import zipfile
from pathlib import Path

import pytest

from docmap.convert import convert
from docmap.slim import slim
from docmap.paths import ROOT

TIMEOUT = 30
_pool = cf.ThreadPoolExecutor(max_workers=2)
BAD = ("error", "needs_ocr", "unsupported")


def run(path, **kw):
    fut = _pool.submit(convert, path, **kw)
    try:
        return fut.result(timeout=TIMEOUT)
    except cf.TimeoutError:  # pragma: no cover
        pytest.fail(f"convert hung > {TIMEOUT}s for {path}")


def msg(r):
    return " ".join(r.warnings).lower()


# ---------------------------------------------------------------- builders
def save_docx(p: Path, build) -> Path:
    import docx
    d = docx.Document()
    build(d)
    d.save(str(p))
    return p


def save_xlsx(p: Path, build) -> Path:
    import openpyxl
    wb = openpyxl.Workbook()
    build(wb)
    wb.save(p)
    return p


def save_pptx(p: Path, build) -> Path:
    from pptx import Presentation
    prs = Presentation()
    build(prs)
    prs.save(p)
    return p


def simple_pdf(p: Path, pages: list[str]) -> Path:
    from fpdf import FPDF
    pdf = FPDF()
    for t in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, t)
    pdf.output(str(p))
    return p


def image_page(pdf, text: str):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (600, 800), "white")
    ImageDraw.Draw(img).text((50, 50), text, fill="black")
    b = io.BytesIO()
    img.save(b, "PNG")
    b.seek(0)
    pdf.add_page()
    pdf.image(b, x=10, y=10, w=190)


# ---------------------------------------------------------------- empty
@pytest.mark.parametrize("ext", [".docx", ".xlsx", ".pptx", ".pdf", ".csv"])
def test_zero_byte_file(tmp_path, ext):
    p = tmp_path / f"empty{ext}"
    p.write_bytes(b"")
    r = run(p)
    if ext == ".csv":
        assert r.status in ("ok", "error", "fallback")
    else:
        assert r.status == "error", r
        assert r.warnings, "error must carry a message"
    assert r.markdown.strip() == ""


def test_valid_empty_docx(tmp_path):
    r = run(save_docx(tmp_path / "e.docx", lambda d: None))
    assert r.status in ("ok", "fallback", "error")
    assert len(r.markdown) < 50


def test_valid_empty_xlsx(tmp_path):
    r = run(save_xlsx(tmp_path / "e.xlsx", lambda wb: None))
    assert r.status in ("ok", "fallback", "error")
    assert len(r.markdown) < 200


def test_valid_empty_pptx(tmp_path):
    r = run(save_pptx(tmp_path / "e.pptx", lambda prs: None))
    assert r.status in ("ok", "fallback", "error")
    assert len(r.markdown) < 200


# ---------------------------------------------------------------- corrupt
@pytest.mark.parametrize("ext", [".docx", ".xlsx", ".pptx", ".pdf"])
def test_random_bytes(tmp_path, ext):
    p = tmp_path / f"junk{ext}"
    p.write_bytes(random.Random(1).randbytes(4096))
    r = run(p)
    assert r.status == "error", r
    assert r.warnings and r.markdown == ""


@pytest.mark.parametrize("maker,ext", [
    (lambda p: save_docx(p, lambda d: d.add_paragraph("hello " * 500)), ".docx"),
    (lambda p: save_xlsx(p, lambda wb: wb.active.append(["a", 1])), ".xlsx"),
    (lambda p: save_pptx(p, lambda prs: prs.slides.add_slide(prs.slide_layouts[0])), ".pptx"),
])
def test_truncated_zip(tmp_path, maker, ext):
    p = maker(tmp_path / f"t{ext}")
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])
    r = run(p)
    assert r.status == "error", r
    assert r.warnings


def test_truncated_pdf(tmp_path):
    p = simple_pdf(tmp_path / "t.pdf", ["Hello world " * 50] * 3)
    d = p.read_bytes()
    p.write_bytes(d[: len(d) // 2])
    r = run(p)
    assert r.status in ("error", "ok", "fallback", "needs_ocr")
    if r.status == "error":
        assert r.warnings


def test_pdf_named_docx(tmp_path):
    p = simple_pdf(tmp_path / "real.pdf", ["Secret figure 4242"])
    q = tmp_path / "fake.docx"
    q.write_bytes(p.read_bytes())
    r = run(q)
    assert r.status == "error" or "4242" in r.markdown
    if r.status == "error":
        assert r.warnings


# ---------------------------------------------------------------- encrypted
def test_encrypted_pdf(tmp_path):
    from pypdf import PdfReader, PdfWriter
    src = simple_pdf(tmp_path / "plain.pdf", ["Top secret 777"])
    w = PdfWriter()
    for pg in PdfReader(str(src)).pages:
        w.add_page(pg)
    w.encrypt("pw123")
    p = tmp_path / "enc.pdf"
    with open(p, "wb") as f:
        w.write(f)
    r = run(p)
    assert r.status == "error", r
    assert r.markdown == ""
    assert r.warnings
    assert re.search(r"encrypt|password|protect", msg(r)), f"unclear message: {r.warnings}"


@pytest.mark.parametrize("ext", [".docx", ".xlsx", ".pptx"])
def test_ooxml_encrypted_container(tmp_path, ext):
    """Office encryption is an OLE/CFB file; mimic with a zip holding EncryptionInfo."""
    p = tmp_path / f"enc{ext}"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("EncryptionInfo", b"\x04\x00\x04\x00" + b"\x00" * 32)
        z.writestr("EncryptedPackage", b"\x00" * 64)
    r = run(p)
    assert r.status == "error", r
    assert r.warnings
    assert re.search(r"encrypt|password|protect", msg(r)), f"unclear message: {r.warnings}"


@pytest.mark.parametrize("ext", [".docx", ".xlsx"])
def test_real_cfb_header_encrypted(tmp_path, ext):
    """Real encrypted Office files start with the CFB magic D0CF11E0."""
    p = tmp_path / f"cfb{ext}"
    p.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 2000)
    r = run(p)
    assert r.status == "error", r
    assert r.warnings


# ---------------------------------------------------------------- unicode
TEXTS = ["مرحبا بالعالم رقم ٤٢", "你好，世界 预算 12345", "Party time 🎉🚀 ok", "Grüße Müller Straße"]


def test_unicode_docx(tmp_path):
    def b(d):
        for t in TEXTS:
            d.add_paragraph(t)
    r = run(save_docx(tmp_path / "u.docx", b))
    assert r.status == "ok"
    for t in TEXTS:
        assert t in r.markdown, t
    assert all(t in slim(r.markdown) for t in TEXTS)


def test_unicode_xlsx(tmp_path):
    def b(wb):
        ws = wb.active
        ws.title = "Übersicht 数据"
        ws.append(["Text", "Num"])
        for i, t in enumerate(TEXTS):
            ws.append([t, i])
    r = run(save_xlsx(tmp_path / "u.xlsx", b))
    assert r.status in ("ok", "fallback")
    for t in TEXTS:
        assert t in r.markdown, t


def test_unicode_pptx(tmp_path):
    def b(prs):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = TEXTS[1]
        s.placeholders[1].text = "\n".join(TEXTS)
    r = run(save_pptx(tmp_path / "u.pptx", b))
    assert r.status in ("ok", "fallback")
    for t in TEXTS:
        assert t in r.markdown, t


@pytest.mark.parametrize("name", [
    "my report final v2.docx",
    "Prüfbericht Größe äöü.docx",
    "名前 报告.docx",
    "long_" + "x" * 150 + ".docx",
])
def test_odd_file_names(tmp_path, name):
    p = save_docx(tmp_path / name, lambda d: d.add_paragraph("Marker sentence 98765"))
    r = run(p)
    assert r.status == "ok", r
    assert "98765" in r.markdown


# ---------------------------------------------------------------- spreadsheets
def test_many_sheets(tmp_path):
    def b(wb):
        wb.active.title = "S0"
        for i in range(1, 60):
            wb.create_sheet(f"S{i}")
        for i, ws in enumerate(wb.worksheets):
            ws.append(["k", "v"])
            ws.append([f"row-{i}", 1000 + i])
    r = run(save_xlsx(tmp_path / "many.xlsx", b))
    assert r.status in ("ok", "fallback")
    for i in range(60):
        assert f"row-{i}" in r.markdown and str(1000 + i) in r.markdown


def test_merged_cells(tmp_path):
    def b(wb):
        ws = wb.active
        ws["A1"] = "Merged title"
        ws.merge_cells("A1:C1")
        ws.append(["a", "b", "c"])
        ws.append([1, 2, 3])
    r = run(save_xlsx(tmp_path / "m.xlsx", b))
    assert r.status in ("ok", "fallback")
    assert "Merged title" in r.markdown
    assert "a" in r.markdown and "3" in r.markdown


def test_formulas_no_cached_value(tmp_path):
    """openpyxl writes no cached values; formula text or blank is acceptable, inputs must survive."""
    def b(wb):
        ws = wb.active
        ws.append(["x", "y", "sum"])
        ws.append([2, 3, "=A2+B2"])
    r = run(save_xlsx(tmp_path / "f.xlsx", b))
    assert r.status in ("ok", "fallback")
    assert "2" in r.markdown and "3" in r.markdown
    print("formula cell rendered as:", [l for l in r.markdown.splitlines() if "2" in l and "3" in l])


def test_formulas_with_cached_values(tmp_path):
    """Patch the sheet XML to carry a cached <v>5</v>, as Excel writes it."""
    p = save_xlsx(tmp_path / "fc.xlsx", lambda wb: (wb.active.append(["x", "y", "sum"]), wb.active.append([2, 3, "=A2+B2"])))
    out = tmp_path / "fc2.xlsx"
    with zipfile.ZipFile(p) as zi, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            d = zi.read(n)
            if n == "xl/worksheets/sheet1.xml":
                s = d.decode()
                s2 = re.sub(r"(<f>A2\+B2</f>)(<v\s*/>|<v></v>)?", r"\1<v>5</v>", s, count=1)
                assert "<v>5</v>" in s2
                d = s2.encode()
            zo.writestr(n, d)
    r = run(out)
    assert r.status in ("ok", "fallback")
    assert re.search(r"\b5\b", r.markdown), "cached formula value must surface"


def test_dates(tmp_path):
    def b(wb):
        ws = wb.active
        ws.append(["when", "n"])
        ws.append([dt.datetime(2024, 3, 15, 10, 30), 1])
        ws.append([dt.date(2023, 12, 31), 2])
    r = run(save_xlsx(tmp_path / "d.xlsx", b))
    assert r.status in ("ok", "fallback")
    assert "2024-03-15" in r.markdown
    assert "2023-12-31" in r.markdown


def test_hidden_sheet_behaviour(tmp_path):
    """Hidden sheets hold real data. Behaviour is printed (see -s) and recorded in the T14 note."""
    def b(wb):
        wb.active.title = "Visible"
        wb.active.append(["v", "VISIBLEDATA"])
        h = wb.create_sheet("Hidden")
        h.append(["h", "HIDDENDATA"])
        h.sheet_state = "hidden"
    r = run(save_xlsx(tmp_path / "h.xlsx", b))
    assert r.status in ("ok", "fallback")
    assert "VISIBLEDATA" in r.markdown
    assert "HIDDENDATA" in r.markdown and "(hidden sheet)" in r.markdown
    assert "hidden" in msg(r)


def test_50k_rows_full_mode(tmp_path):
    N = 50_000

    def b(wb):
        ws = wb.active
        ws.title = "Big"
        ws.append(["id", "label", "value"])
        for i in range(N):
            ws.append([i, f"lbl{i}", i * 1.5])
    p = save_xlsx(tmp_path / "big.xlsx", b)
    r = run(p, mode="full")
    assert r.status in ("ok", "fallback"), r
    assert not r.digested
    rows = len(re.findall(r"^\|\s*\d+\s*\|\s*lbl\d+\s*\|", r.markdown, re.M))
    assert rows == N, f"rows in MD {rows} != {N} (silent data loss)"
    assert "lbl49999" in r.markdown
    # size warning, only if the module exposes one (T06 adds token_count / too_large)
    if hasattr(r, "too_large"):
        from docmap.tokens import count
        if count(r.markdown) > 128_000:
            assert r.too_large, "large output must be flagged"


def test_default_mode_is_full(tmp_path):
    def b(wb):
        ws = wb.active
        ws.append(["id", "name"])
        for i in range(500):
            ws.append([i, f"nm{i}"])
    r = run(save_xlsx(tmp_path / "d500.xlsx", b))
    assert not r.digested, "default mode must not digest (EGI DECISION)"
    assert "nm499" in r.markdown


# ---------------------------------------------------------------- pptx
def test_pptx_notes_tables_empty(tmp_path):
    from pptx.util import Inches

    def b(prs):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = "Plan"
        s.placeholders[1].text = "Body point"
        s.notes_slide.notes_text_frame.text = "NOTE-ALPHA-31337"
        s2 = prs.slides.add_slide(prs.slide_layouts[5])
        s2.shapes.title.text = "Numbers"
        t = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(5), Inches(1)).table
        t.cell(0, 0).text = "Area"; t.cell(0, 1).text = "Cost"
        t.cell(1, 0).text = "Ops"; t.cell(1, 1).text = "8,675,309"
        prs.slides.add_slide(prs.slide_layouts[6])  # blank slide
    r = run(save_pptx(tmp_path / "p.pptx", b))
    assert r.status in ("ok", "fallback")
    assert "NOTE-ALPHA-31337" in r.markdown, "speaker notes lost"
    assert "8,675,309" in r.markdown, "slide table lost"
    assert "Body point" in r.markdown


# ---------------------------------------------------------------- docx
def test_docx_nested_table(tmp_path):
    def b(d):
        t = d.add_table(rows=1, cols=2)
        t.cell(0, 0).text = "OUTER-A"
        inner = t.cell(0, 1).add_table(rows=2, cols=2)
        inner.cell(0, 0).text = "INNER-1"
        inner.cell(1, 1).text = "INNER-4"
    r = run(save_docx(tmp_path / "n.docx", b))
    assert r.status in ("ok", "fallback")
    assert "OUTER-A" in r.markdown
    assert "INNER-1" in r.markdown and "INNER-4" in r.markdown, "nested table content lost"


def test_docx_header_footer(tmp_path):
    def b(d):
        d.add_paragraph("Body text")
        s = d.sections[0]
        s.header.paragraphs[0].text = "HEADER-TEXT-XYZ"
        s.footer.paragraphs[0].text = "FOOTER-TEXT-XYZ"
    r = run(save_docx(tmp_path / "hf.docx", b))
    assert r.status in ("ok", "fallback")
    assert "Body text" in r.markdown
    print("header kept:", "HEADER-TEXT-XYZ" in r.markdown, "footer kept:", "FOOTER-TEXT-XYZ" in r.markdown)


def test_docx_footnotes(tmp_path):
    p = save_docx(tmp_path / "fn.docx", lambda d: d.add_paragraph("Claim text"))
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    fn_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes {W}>'
              '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
              '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
              '<w:footnote w:id="1"><w:p><w:r><w:t>FOOTNOTE-SOURCE-5150</w:t></w:r></w:p></w:footnote></w:footnotes>')
    out = tmp_path / "fn2.docx"
    with zipfile.ZipFile(p) as zi, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            d = zi.read(n)
            if n == "[Content_Types].xml":
                d = d.decode().replace("</Types>", '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>').encode()
            if n == "word/document.xml":
                d = d.decode().replace("Claim text</w:t></w:r>", 'Claim text</w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r>', 1).encode()
            if n == "word/_rels/document.xml.rels":
                d = d.decode().replace("</Relationships>", '<Relationship Id="rIdFn1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/></Relationships>').encode()
            zo.writestr(n, d)
        zo.writestr("word/footnotes.xml", fn_xml)
    r = run(out)
    assert r.status in ("ok", "fallback")
    assert "Claim text" in r.markdown
    print("footnote kept:", "FOOTNOTE-SOURCE-5150" in r.markdown)


def test_docx_tracked_changes(tmp_path):
    p = save_docx(tmp_path / "tc.docx", lambda d: d.add_paragraph("PLACEHOLDER"))
    out = tmp_path / "tc2.docx"
    ins = ('<w:ins w:id="1" w:author="a" w:date="2024-01-01T00:00:00Z"><w:r><w:t>INSERTED-WORDS</w:t></w:r></w:ins>'
           '<w:del w:id="2" w:author="a" w:date="2024-01-01T00:00:00Z"><w:r><w:delText>DELETED-WORDS</w:delText></w:r></w:del>')
    with zipfile.ZipFile(p) as zi, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            d = zi.read(n)
            if n == "word/document.xml":
                s = d.decode()
                s2 = re.sub(r"<w:r>(?:(?!</w:r>).)*PLACEHOLDER(?:(?!</w:r>).)*</w:r>", "<w:r><w:t>Kept words </w:t></w:r>" + ins, s, count=1, flags=re.S)
                assert s2 != s
                d = s2.encode()
            zo.writestr(n, d)
    r = run(out)
    assert r.status in ("ok", "fallback")
    assert "Kept words" in r.markdown
    print("tracked insert kept:", "INSERTED-WORDS" in r.markdown, "tracked delete kept:", "DELETED-WORDS" in r.markdown)


# ---------------------------------------------------------------- pdf
def test_pdf_two_columns(tmp_path):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for x, tag in ((10, "LEFTCOL"), (110, "RIGHTCOL")):
        pdf.set_xy(x, 20)
        pdf.multi_cell(85, 6, " ".join(f"{tag}{i}" for i in range(40)))
    p = tmp_path / "cols.pdf"
    pdf.output(str(p))
    r = run(p)
    assert r.status in ("ok", "fallback")
    for i in (0, 39):
        assert f"LEFTCOL{i}" in r.markdown and f"RIGHTCOL{i}" in r.markdown
    print("columns interleaved:", r.markdown.find("RIGHTCOL0") < r.markdown.find("LEFTCOL39"))


def test_pdf_mixed_scanned_pages(tmp_path):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page(); pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 6, "TEXTPAGE-ONE the quick brown fox 11111 " * 10)
    image_page(pdf, "scanned two")
    pdf.add_page(); pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 6, "TEXTPAGE-THREE lazy dog 33333 " * 10)
    p = tmp_path / "mixed.pdf"
    pdf.output(str(p))
    r = run(p)
    print("mixed pdf status:", r.status, r.warnings)
    if r.status == "needs_ocr":
        assert "ocr" in msg(r)
    else:
        assert "TEXTPAGE-ONE" in r.markdown and "TEXTPAGE-THREE" in r.markdown
        assert re.search(r"ocr|scanned|image", msg(r)), "image-only page must be flagged, not silently dropped"


def test_pdf_fully_scanned(tmp_path):
    from fpdf import FPDF
    pdf = FPDF()
    image_page(pdf, "scan")
    p = tmp_path / "scan.pdf"
    pdf.output(str(p))
    r = run(p)
    assert r.status == "needs_ocr"
    assert "ocr" in msg(r)


# ---------------------------------------------------------------- unsupported
@pytest.mark.parametrize("name,data", [
    pytest.param("notes.txt", b"hello 123"),
    pytest.param("a.zip", b"PK\x05\x06" + b"\x00" * 18),
    ("tool.exe", b"MZ\x90\x00" + b"\x00" * 100),
    pytest.param("page.html", b"<html><script>alert(1)</script></html>"),
    pytest.param("noext", b"abc"),
])
def test_unsupported_extension(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    r = run(p)
    assert r.status in ("error", "unsupported"), r
    assert r.warnings, "needs a clear message"
    assert r.markdown == ""


def test_exe_renamed_docx_not_executed(tmp_path):
    p = tmp_path / "evil.docx"
    p.write_bytes(b"MZ\x90\x00" + b"\x00" * 200)
    r = run(p)
    assert r.status == "error"


# ---------------------------------------------------------------- slim
SAMPLE_MD = sorted(glob.glob(str(ROOT / "data" / "md" / "*.md")))
SMALL = [f for f in SAMPLE_MD if os.path.getsize(f) < 400_000][:8]


def _numbers(s):
    return re.findall(r"\d+(?:[.,]\d+)*", s)


@pytest.mark.parametrize("f", SMALL or [None])
def test_slim_corpus(f):
    if f is None:
        pytest.skip("no corpus md")
    text = Path(f).read_text(encoding="utf-8")
    s1 = slim(text)
    assert slim(s1) == s1, "slim not idempotent"
    h_before = {re.sub(r"\s+", " ", m.strip().lstrip("#").strip()).lower() for m in re.findall(r"^#{1,6} .+$", text, re.M)}
    out_l = re.sub(r"\s+", " ", s1).lower()
    missing_h = [h for h in h_before if h and h not in out_l]
    assert not missing_h, missing_h[:5]
    nb, na = set(_numbers(text)), set(_numbers(s1))
    lost = sorted(nb - na)
    assert len(lost) <= max(2, 0.001 * len(nb)), f"numbers lost: {lost[:15]}"


def test_slim_idempotent_synthetic():
    md = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n|  |  |\n\n* x\n* x\n\n**bold** [l](http://e.com)\n\nPage 3\n\n" + "Footer line repeated\n\n" * 6
    s = slim(md)
    assert slim(s) == s
    assert "1" in s and "2" in s and "# T" in s
