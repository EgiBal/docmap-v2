"""Token counting and the naive baselines ("what people paste today")."""
from __future__ import annotations

import io
import re
import zipfile
from functools import lru_cache
from pathlib import Path

import tiktoken


@lru_cache(maxsize=4)
def _enc(name: str):
    return tiktoken.get_encoding(name)


def count(text: str, enc: str = "o200k_base") -> int:
    # disallowed_special=() so literal "<|endoftext|>" in documents does not raise
    return len(_enc(enc).encode(text, disallowed_special=()))


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def _docx(path: Path) -> str:
    import docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append("\t".join(c.text for c in row.cells))
    return "\n".join(parts)


def _xlsx(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"# {ws.title}")
        for row in ws.iter_rows(values_only=True):
            out.append(",".join("" if v is None else str(v) for v in row))
    return "\n".join(out)


def _pptx(path: Path) -> str:
    from pptx import Presentation

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == 6:  # group
                yield from walk(sh.shapes)
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                yield sh.text_frame.text
            if getattr(sh, "has_table", False) and sh.has_table:
                for r in sh.table.rows:
                    yield "\t".join(c.text for c in r.cells)

    out = []
    for s in Presentation(str(path)).slides:
        out.extend(walk(s.shapes))
    return "\n".join(out)


def naive_dump(path: str | Path) -> str:
    """Baseline: plain text extraction a person would paste into an LLM."""
    path = Path(path)
    ext = path.suffix.lower()
    fn = {".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}.get(ext)
    if fn is None:
        raise ValueError(f"unsupported format: {ext}")
    return fn(path)


def raw_xml_tokens(path: str | Path, enc: str = "o200k_base") -> int:
    """UPPER BOUND (not a realistic baseline): tokens of all XML text parts
    inside an OOXML zip (docx/xlsx/pptx). Counts markup, not just text."""
    total = 0
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith((".xml", ".rels")):
                total += count(z.read(n).decode("utf-8", "replace"), enc)
    return total


# --- upload estimate (what pasting/uploading the ORIGINAL file into an LLM chat costs) ---
# Docs: https://docs.claude.com/en/docs/build-with-claude/pdf-support  (redirects to platform.claude.com)
#       https://docs.claude.com/en/docs/build-with-claude/vision
# PDF: each page = its extracted text tokens + one page image. Image cost = ceil(w/28)*ceil(h/28)
# visual tokens, at most 1,568 per page (Standard tier; the API fits page images to that limit).
# Page images are assumed rendered at PDF_DPI. This is an ESTIMATE, not an API call.
PDF_DPI = 150
IMG_TOKEN_CAP = 1568
PATCH = 28


def image_tokens(w_px: float, h_px: float, cap: int = IMG_TOKEN_CAP, max_edge: int = 1568) -> int:
    import math

    s = min(1.0, max_edge / max(w_px, h_px))
    w, h = w_px * s, h_px * s
    t = math.ceil(w / PATCH) * math.ceil(h / PATCH)
    while t > cap:  # shrink until under the visual-token cap
        s *= 0.97
        t = math.ceil(w_px * s / PATCH) * math.ceil(h_px * s / PATCH)
    return t


def pdf_image_tokens(path: str | Path) -> tuple[int, int]:
    """(pages, total page-image tokens) from page sizes in pypdf."""
    from pypdf import PdfReader

    total, n = 0, 0
    for p in PdfReader(str(path)).pages:
        box = p.mediabox
        w, h = float(box.width), float(box.height)
        if (p.get("/Rotate") or 0) % 180:
            w, h = h, w
        total += image_tokens(w * PDF_DPI / 72, h * PDF_DPI / 72)
        n += 1
    return n, total


def upload_estimate(path: str | Path, naive_tokens: int) -> tuple[int, str]:
    """Estimated tokens to upload the original file. Returns (tokens, basis)."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        pages, img = pdf_image_tokens(path)
        return naive_tokens + img, f"text + {pages} page images"
    return naive_tokens, "= naive (text extraction assumed)"
