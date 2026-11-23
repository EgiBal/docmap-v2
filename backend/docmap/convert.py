"""Convert office/PDF files to Markdown. anydoc first, markitdown as fallback.

Hosted OCR is never called: ocr is always "reject".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

MAX_FALLBACK_BYTES = 8_000_000  # markitdown took ~2 min on a 12 MB xlsx

ALLOWED_EXTS = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".pptx", ".ppt", ".odt", ".ods", ".odp",
                ".rtf", ".csv", ".epub")
OOXML_EXTS = (".docx", ".xlsx", ".xlsm", ".pptx")
ENCRYPTED_MSG = "encrypted: remove the password and upload again"
CFB_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")

Status = Literal["ok", "digest", "needs_ocr", "fallback", "error", "unsupported"]
Mode = Literal["auto", "full", "digest"]


@dataclass
class ConvertResult:
    markdown: str
    status: Status
    converter: str
    warnings: list[str] = field(default_factory=list)
    digested: list[str] = field(default_factory=list)  # sheet names that got a digest


def _markitdown(path: Path) -> str:
    from markitdown import MarkItDown

    return MarkItDown().convert(str(path)).text_content


def _anydoc_version() -> str:
    from importlib.metadata import version

    return version("firecrawl-anydoc")


def _try_digest(path: Path, mode: str, digest_rows: int, warnings: list[str]) -> ConvertResult | None:
    from . import digest as dg

    try:
        sheets = dg.analyse_workbook(path, digest_rows)
    except Exception as e:
        warnings.append(f"digest scan failed: {type(e).__name__}: {e}")
        return None
    is_csv = path.suffix.lower() == ".csv"
    if mode == "auto" and not is_csv and not any(s.rows > digest_rows for s in sheets):
        return None  # nothing big: normal converter keeps the full tables
    md, done = dg.render_workbook(sheets, path.name, mode, digest_rows)
    return ConvertResult(md, "digest" if done else "ok", "docmap.digest", warnings, done)


def _encrypted_office(path: Path) -> bool:
    """Office encryption: an OLE/CFB container under an OOXML extension, or a zip with EncryptionInfo."""
    import zipfile

    try:
        with path.open("rb") as f:
            head = f.read(8)
        if head == CFB_MAGIC:
            return True
        if head[:2] == b"PK":
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
            return "EncryptionInfo" in names or "EncryptedPackage" in names
    except Exception:
        pass
    return False


def _pdf_ocr_pages(path: Path) -> list[int]:
    """1-based numbers of pages with no text layer but with an image (scans mixed into a text PDF)."""
    try:
        from pypdf import PdfReader

        out = []
        for i, pg in enumerate(PdfReader(str(path)).pages, 1):
            if (pg.extract_text() or "").strip():
                continue
            try:
                has_img = len(pg.images) > 0
            except Exception:
                has_img = True
            if has_img:
                out.append(i)
        return out
    except Exception:
        return []


def _hidden_sheets(path: Path) -> list[str]:
    try:
        import openpyxl

        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            return [ws.title for ws in wb.worksheets if ws.sheet_state != "visible"]
        finally:
            wb.close()
    except Exception:
        return []


def convert(path: str | Path, mode: Mode = "full", digest_rows: int | None = None) -> ConvertResult:
    """mode: 'full' (default, Egi's decision) converts every row; 'auto' digests sheets over digest_rows
    (opt-in, lossy); 'digest' always digests."""
    path = Path(path)
    warnings: list[str] = []
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTS:
        return ConvertResult("", "unsupported", "none",
                             [f"unsupported file type {ext or '(no extension)'}: allowed are "
                              + ", ".join(e.lstrip(".") for e in ALLOWED_EXTS)])
    if ext in OOXML_EXTS and _encrypted_office(path):
        return ConvertResult("", "error", "none", [ENCRYPTED_MSG])
    if digest_rows is None:
        from .digest import DIGEST_ROWS as digest_rows
    if path.suffix.lower() in (".xlsx", ".csv") and mode != "full":
        r = _try_digest(path, mode, digest_rows, warnings)
        if r is not None:
            return r
    try:
        import anydoc
    except Exception as e:  # pragma: no cover
        anydoc = None
        warnings.append(f"anydoc import failed: {e}")

    if anydoc is not None:
        try:
            md = anydoc.to_markdown(path, ocr="reject")
            if ext == ".pdf":
                pages = _pdf_ocr_pages(path)
                if pages:
                    warnings.append(f"pages {pages} are scanned images and need OCR (not converted). "
                                    "The text on the other pages is kept")
            elif ext in (".xlsx", ".xlsm"):
                hidden = _hidden_sheets(path)
                if hidden:
                    from . import digest as dg
                    md += "\n" + dg.full_stream_markdown(path, only=hidden, label=" (hidden sheet)")
                    warnings.append(f"hidden sheets included in full: {hidden}")
            return ConvertResult(md, "ok", "anydoc " + _anydoc_version(), warnings)
        except anydoc.NeedsOcrError as e:
            pages = getattr(e, "pages", None)
            warnings.append(f"scanned/image-only pages need OCR: {pages}")
            return ConvertResult("", "needs_ocr", "anydoc", warnings)
        except Exception as e:
            warnings.append(f"anydoc failed: {type(e).__name__}: {e}")

    if path.suffix.lower() in (".xlsx", ".csv"):  # anydoc resource limit etc.: stream every row ourselves
        try:
            from . import digest as dg
            md = dg.full_stream_markdown(path)
            warnings.append("converted with the streaming full-sheet fallback (every row kept)")
            return ConvertResult(md, "fallback", "docmap.digest.full_stream", warnings)
        except Exception as e:
            warnings.append(f"streaming fallback failed: {type(e).__name__}: {e}")

    if path.stat().st_size > MAX_FALLBACK_BYTES:
        warnings.append(f"file over {MAX_FALLBACK_BYTES // 1_000_000} MB: markitdown fallback skipped (too slow)")
        return ConvertResult("", "error", "none", warnings)
    try:
        md = _markitdown(path)
        return ConvertResult(md, "fallback", "markitdown", warnings)
    except Exception as e:
        warnings.append(f"markitdown failed: {type(e).__name__}: {e}")
        return ConvertResult("", "error", "none", warnings)
