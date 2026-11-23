"""Token report CLI: uv run python -m docmap.report <folder> --out <md>"""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from .convert import convert
from .slim import slim
from .tokens import PDF_DPI, count, naive_dump, raw_xml_tokens, upload_estimate
from .paths import ROOT

EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}
MD_DIR = ROOT / "data" / "md"


def _pct(new: int, base: int) -> float | None:
    return None if base <= 0 else 100.0 * (base - new) / base


def analyse(path: Path, write_md: bool = True, mode: str = "auto") -> dict:
    row = {"file": path.name, "format": path.suffix.lower().lstrip("."), "status": "", "naive": None,
           "anydoc": None, "slim": None, "upload": None, "saved_up": None, "digested": [], "xml": None, "saved": None, "ms": 0.0, "note": ""}
    try:
        row["naive"] = count(naive_dump(path))
    except Exception as e:
        row["note"] = f"naive failed: {type(e).__name__}"
    if row["format"] != "pdf":
        try:
            row["xml"] = raw_xml_tokens(path)
        except Exception:
            pass
    if row["naive"] is not None:
        try:
            row["upload"] = upload_estimate(path, row["naive"])[0]
        except Exception as e:
            row["note"] += f" upload_est failed: {type(e).__name__}"
    t0 = time.perf_counter()
    res = convert(path, mode=mode)
    row["digested"] = res.digested
    s = slim(res.markdown) if res.markdown else ""
    row["ms"] = (time.perf_counter() - t0) * 1000
    row["status"] = res.status
    if res.warnings:
        row["note"] = (row["note"] + " " + "; ".join(w[:80] for w in res.warnings)).strip()
    if res.status in ("ok", "digest", "fallback"):
        row["anydoc"] = count(res.markdown)
        row["slim"] = count(s)
        row["saved"] = _pct(row["slim"], row["naive"] or 0)
        row["saved_up"] = _pct(row["slim"], row["upload"] or 0)
        if write_md:
            MD_DIR.mkdir(parents=True, exist_ok=True)
            (MD_DIR / f"{path.name}.md").write_text(s, encoding="utf-8")
    return row


def _excl(ok: list[dict]) -> str:
    big = max(ok, key=lambda r: r["naive"])
    g = [r for r in ok if r is not big]
    tn, tu, ts = (sum(r[k] for r in g) for k in ("naive", "upload", "slim"))
    return (f"- excluding the largest file ({big['file']}, {big['naive']} naive tokens): naive {tn} -> slim {ts} "
            f"(**{_pct(ts, tn):.1f}% saved vs naive**, {_pct(ts, tu):.1f}% vs upload_est)")


def build_report(rows: list[dict], title: str) -> str:
    def f(v):
        return "-" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v))

    L = [f"# {title}", "",
         "Tokens: tiktoken o200k_base. Baselines:",
         "- `naive` = plain text dump (pypdf / python-docx / openpyxl / python-pptx).",
         "- `upload_est` = ESTIMATE of uploading the original file to an LLM chat. PDF = naive text + one image per page "
         f"(ceil(w/28)*ceil(h/28) visual tokens, max 1568 per page, pages rendered at {PDF_DPI} dpi from pypdf page sizes). "
         "docx/xlsx/pptx = assumed text extraction, so upload_est = naive. Not a measured API count.",
         "  Sources: https://docs.claude.com/en/docs/build-with-claude/pdf-support and "
         "https://docs.claude.com/en/docs/build-with-claude/vision (both redirect to platform.claude.com).",
         "- `pack` (per-topic context pack): see eval metrics.json (built by the topics task, not here).",
         "- `xml` = raw OOXML XML text, an UPPER BOUND, not a realistic baseline.", "",
         "| file | fmt | status | naive | upload_est (estimate) | slim MD | xml (upper bound) | % saved vs naive | % saved vs upload_est | digested sheets | ms |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['file']} | {r['format']} | {r['status']} | {f(r['naive'])} | {f(r['upload'])} | "
                 f"{f(r['slim'])} | {f(r['xml'])} | {f(r['saved'])} | {f(r['saved_up'])} | "
                 f"{', '.join(r['digested']) or '-'} | {r['ms']:.0f} |")
    ok = [r for r in rows if r["slim"] is not None and r["naive"]]
    if ok:
        tn, ts, ta = sum(r["naive"] for r in ok), sum(r["slim"] for r in ok), sum(r["anydoc"] for r in ok)
        tu = sum(r["upload"] for r in ok)
        L += ["", "## Totals (converted files only)", "",
              "| baseline | tokens | slim MD tokens | saved |", "|---|---|---|---|",
              f"| naive | {tn} | {ts} | **{_pct(ts, tn):.1f}%** |",
              f"| upload_est (estimate) | {tu} | {ts} | **{_pct(ts, tu):.1f}%** |", "",
              f"- files converted: {len(ok)} of {len(rows)}",
              _excl(ok),
              f"- converter output before slim: {ta} tokens ({_pct(ta, tn):.1f}% vs naive)",
              f"- total time: {sum(r['ms'] for r in rows):.0f} ms", "", "## Per-format medians", "",
              "| fmt | files | median % saved vs naive | median % saved vs upload_est | median ms |", "|---|---|---|---|---|"]
        for fmt in sorted({r["format"] for r in ok}):
            g = [r for r in ok if r["format"] == fmt]
            L.append(f"| {fmt} | {len(g)} | {statistics.median(r['saved'] for r in g):.1f} | "
                     f"{statistics.median(r['saved_up'] for r in g):.1f} | {statistics.median(r['ms'] for r in g):.0f} |")
    L += ["", "## Per-topic context pack", "", "Per-topic context pack: see eval metrics.json"]
    flagged = [r for r in rows if r["status"] not in ("ok", "digest")]
    if flagged:
        L += ["", "## Not plain ok", ""] + [f"- {r['file']}: {r['status']} {r['note']}" for r in flagged]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="DocMap token report")
    ap.add_argument("--mode", default="auto", choices=["auto", "full", "digest"])
    ap.add_argument("--no-md", action="store_true", help="do not write slim .md files")
    a = ap.parse_args()
    files = sorted(p for p in Path(a.folder).rglob("*") if p.suffix.lower() in EXTS)
    rows = [analyse(p, not a.no_md, a.mode) for p in files]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(rows, a.title), encoding="utf-8")
    print(f"{len(rows)} files -> {out}")


if __name__ == "__main__":
    main()
