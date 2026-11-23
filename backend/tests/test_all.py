import re
from pathlib import Path

import pytest

from docmap.convert import convert
from docmap.slim import slim
from docmap.tokens import count, naive_dump, raw_xml_tokens
import fixtures as fx


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("fx")
    return {
        "docx": fx.make_docx(d / "a.docx"),
        "xlsx": fx.make_xlsx(d / "a.xlsx"),
        "pptx": fx.make_pptx(d / "a.pptx"),
        "pdf": fx.make_pdf(d / "a.pdf"),
        "scan": fx.make_scanned_pdf(d / "s.pdf"),
    }


@pytest.mark.parametrize("fmt,needles", [
    ("docx", ["Quarterly Report", "12.5%", "$4,200,000", "North", "120"]),
    ("xlsx", ["Widget 20", "199.8", "Total widgets sold: 210"]),
    ("pptx", ["Roadmap 2027", "1,234,567", "42 pilot customers"]),
    ("pdf", ["Section 1", "1234 EUR", "4234 EUR"]),
])
def test_convert_and_slim_keep_content(files, fmt, needles):
    r = convert(files[fmt])
    assert r.status == "ok" and r.converter.startswith("anydoc")
    s = slim(r.markdown)
    for n in needles:
        assert n in r.markdown, n
        assert n in s, f"slim lost {n!r}"
    assert count(s) <= count(r.markdown)


def test_needs_ocr_never_hosted(files, monkeypatch):
    import anydoc

    real = anydoc.to_markdown
    seen = {}

    def spy(path, **kw):
        seen.update(kw)
        return real(path, **kw)

    monkeypatch.setattr(anydoc, "to_markdown", spy)
    r = convert(files["scan"])
    assert r.status == "needs_ocr" and r.markdown == ""
    assert seen.get("ocr") == "reject"


def test_fallback_on_anydoc_error(files, monkeypatch):
    import anydoc

    def boom(*a, **k):
        raise anydoc.MalformedError("x") if False else RuntimeError("boom")

    monkeypatch.setattr(anydoc, "to_markdown", boom)
    r = convert(files["pptx"])
    assert r.status == "fallback" and r.converter == "markitdown"
    assert "Roadmap 2027" in r.markdown


def test_error_status_on_garbage(tmp_path):
    p = tmp_path / "bad.docx"
    p.write_bytes(b"not a zip")
    assert convert(p).status in ("error", "fallback")


def test_naive_and_xml(files):
    for k in ("docx", "xlsx", "pptx", "pdf"):
        assert count(naive_dump(files[k])) > 0
    assert raw_xml_tokens(files["docx"]) > count(naive_dump(files["docx"]))


# ---- slim safety ----
def test_slim_keeps_numbers_and_headings():
    md = "# Title 2024\n\n## Section 3.1\n\nTotal: 1,234,567.89 EUR (12.5%)\n\n- item 42\n"
    s = slim(md)
    for t in ["# Title 2024", "## Section 3.1", "1,234,567.89", "12.5%", "- item 42"]:
        assert t in s


def test_slim_page_headers_footers():
    pages = []
    for i in range(1, 6):
        pages.append(f"ACME Confidential Report\n\nBody text for page number {i} unique{i}.\n\nPage {i} of 5\n")
    s = slim("\n".join(pages))
    assert s.count("ACME Confidential Report") == 1
    assert "Page 3 of 5" not in s
    for i in range(1, 6):
        assert f"unique{i}" in s and f"number {i}" in s


def test_slim_does_not_drop_long_similar_paragraphs():
    md = "\n\n".join(f"Net income was {i*1000+234} EUR in section {i} of the annual report overall." for i in range(1, 6))
    s = slim(md)
    for i in range(1, 6):
        assert f"{i*1000+234}" in s


def test_slim_tables():
    md = "|   Item   |  Qty  |   |\n| --- | --- | --- |\n|   A   |  10  |   |\n|   |   |   |\n| ---- | --- | --- |\n|  B  |  20.5  |   |\n"
    s = slim(md)
    assert s.splitlines()[0] == "|Item|Qty|"
    assert "|A|10|" in s and "|B|20.5|" in s
    assert s.count("\n") == 4  # header, sep, 2 rows


def test_slim_images_and_base64():
    b64 = "A" * 300
    md = f"Before ![img](data:image/png;base64,{b64}) after\n\n![Chart of sales](x.png)\n\n![](y.png)\n{b64}\n"
    s = slim(md)
    assert "base64" not in s and b64 not in s
    assert "Before" in s and "after" in s and "[image: Chart of sales]" in s


def test_slim_bullets_whitespace_dedupe():
    md = "* a\n+ b\n• c\n\n\n\n\nline   with    spaces   \nsame\nsame\nsame\n"
    s = slim(md)
    assert "- a\n- b\n- c" in s
    assert "\n\n\n" not in s
    assert "line with spaces\n" in s
    assert s.count("same") == 1


def test_slim_deterministic_and_idempotent():
    md = open(__file__, encoding="utf-8").read()
    assert slim(md) == slim(md)  # idempotence is not guaranteed (second pass may strip more)


def test_slim_code_fence_untouched():
    md = "```\na    b\n\n\n\nc\n```\n"
    assert "a    b" in slim(md)


def test_slim_links_bold_escapes():
    md = "See [Contents](#contents) and [www.gov.uk/x](http://www.gov.uk/x) and [Guide](https://a.b/c).\n\n**Bold** note 14 06 04\\* done\n"
    s = slim(md)
    assert "(#contents)" not in s and "See Contents and" in s
    assert "www.gov.uk/x" in s and "http://www.gov.uk/x" not in s
    assert "Guide (https://a.b/c)" in s
    assert "Bold note 14 06 04* done" in s
