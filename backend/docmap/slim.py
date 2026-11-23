"""Token diet for Markdown. Deterministic; aims to keep all real content.

Steps: strip images/base64, simplify links, strip bold markers and needless
escapes, keep code fences verbatim, normalise bullets, collapse whitespace,
rebuild tables (drop empty rows/cols and separator-only cells, compact pipes),
drop page-number lines, drop lines that repeat many times (headers/footers;
first occurrence kept), dedupe identical consecutive lines, collapse blank lines.
"""
from __future__ import annotations

import re
from collections import Counter

_DATA_URI = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=\s]{20,}")
_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{200,}={0,2}(?![A-Za-z0-9+/=])")
_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.I)
_BULLET = re.compile(r"^(\s*)(?:[*+•◦▪●·–—]|-)\s+(?=\S)")
_PAGE_NUM = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*(?:of|/)\s*\d+|[-–—]\s*\d+\s*[-–—])\s*$",
    re.I,
)
_SEP_CELL = re.compile(r"^:?-{1,}:?$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]*)\)")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ESC = re.compile(r"(?<=\S)\\([*_.()])")  # mid-line only, so no accidental bullets
_HRULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_HARD_BREAK = re.compile(r"\\\n")

MIN_REPEATS = 4          # a line seen this often is a header/footer candidate
MAX_BOILER_LEN = 100     # only short lines can be page headers/footers
MIN_BOILER_LEN = 8       # very short lines ("Yes", "N/A") are never boilerplate
_SKIP_PREFIX = ("#", "- ", ">")

# "pipe"    = | a | b |  with  |---|---|  separator   (classic Markdown)
# "compact" = |a|b|      with  |-|-|      separator   (still valid Markdown)
# "bare"    = header row then rows as a|b (no edge pipes, no separator row)
TABLE_STYLE = "compact"


def _clean_image(m: re.Match) -> str:
    alt = m.group(1).strip()
    # keep alt text only when it carries information
    if alt and not re.fullmatch(r"(image|img|picture|figure|graphic)?\s*\d*", alt, re.I):
        return f"[image: {alt}]"
    return ""


def _link(m: re.Match) -> str:
    text, url = m.group(1).strip(), m.group(2)
    if url.startswith("#") or not url:
        return text  # in-document anchor: the text is enough
    bare = re.sub(r"^(https?://|mailto:)", "", url).rstrip("/")
    if text.rstrip("/") in (url.rstrip("/"), bare):
        return text or url
    return f"{text} ({url})" if text else url


def _row(cells: list[str]) -> str:
    if TABLE_STYLE == "pipe":
        return "| " + " | ".join(cells) + " |"
    if TABLE_STYLE == "compact":
        return "|" + "|".join(cells) + "|"
    return "|".join(cells)


def _split_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "\\|"
            i += 2
            continue
        if s[i] == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += s[i]
        i += 1
    cells.append(cur.strip())
    return [re.sub(r"\s+", " ", c) for c in cells]


def _is_sep_row(cells: list[str]) -> bool:
    return bool(cells) and all(_SEP_CELL.match(c) for c in cells)


def _slim_table(rows: list[str]) -> list[str]:
    parsed = [_split_cells(r) for r in rows]
    width = max(len(r) for r in parsed)
    parsed = [r + [""] * (width - len(r)) for r in parsed]
    has_sep = len(parsed) > 1 and _is_sep_row(parsed[1])
    header = parsed[0] if has_sep else None
    body = parsed[2:] if has_sep else parsed
    # separator-only cells in body ("---", "-") are noise -> empty
    body = [[("" if _SEP_CELL.match(c) else c) for c in r] for r in body]
    body = [r for r in body if any(r)]
    all_rows = ([header] if header is not None else []) + body
    if not any(any(r) for r in all_rows):
        return []
    keep = [j for j in range(width) if any(r[j] for r in all_rows)]
    header = [header[j] for j in keep] if header is not None else None
    body = [[r[j] for j in keep] for r in body]
    n = len(keep)
    out: list[str] = []
    if header is not None and any(header):
        out.append(_row(header))
        if TABLE_STYLE == "pipe":
            out.append("|" + "---|" * n)
        elif TABLE_STYLE == "compact":
            out.append("|" + "-|" * n)
        out.extend(_row(r) for r in body)
    elif n == 1:
        out.extend(r[0] for r in body)  # single column, no header: plain lines
    else:
        out.extend(_row(r) for r in body)  # empty header dropped; keep data rows
    return out


def _norm_key(line: str) -> str:
    # Exact match only (case/space-insensitive). Digit-normalising was tried and
    # dropped real content ("Total: 100" vs "Total: 200"), so it is not used.
    return re.sub(r"\s+", " ", line.strip()).lower()


def _is_boiler_candidate(kind: str, t: str) -> bool:
    s = t.strip()
    return kind == "text" and bool(s) and len(s) <= MAX_BOILER_LEN and not t.lstrip().startswith(_SKIP_PREFIX)


def slim(markdown: str) -> str:
    if not markdown:
        return ""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("​", "")
    text = _DATA_URI.sub("", text)
    text = _IMG.sub(_clean_image, text)
    text = _HTML_IMG.sub("", text)
    text = _B64_RUN.sub("", text)
    text = _LINK.sub(_link, text)
    text = _BOLD.sub(r"\2", text)
    text = _ESC.sub(r"\1", text)
    text = _HARD_BREAK.sub("\n", text)

    lines = text.split("\n")
    items: list[tuple[str, str]] = []  # kind: code | text | table
    in_code = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _FENCE.match(ln):
            in_code = not in_code
            items.append(("code", ln.rstrip()))
            i += 1
            continue
        if in_code:
            items.append(("code", ln.rstrip()))
            i += 1
            continue
        if _TABLE_ROW.match(ln):
            j = i
            while j < len(lines) and _TABLE_ROW.match(lines[j]) and not _FENCE.match(lines[j]):
                j += 1
            for r in _slim_table(lines[i:j]):
                items.append(("table", r) if "|" in r else ("text", r))
            i = j
            continue
        if _HRULE.match(ln):
            i += 1
            continue
        m = re.match(r"^(\s*)(.*)$", ln.rstrip())
        indent = m.group(1).replace("\t", "  ")
        rest = re.sub(r"[ \t]{2,}", " ", m.group(2)).replace("\t", " ")
        ln = _BULLET.sub(lambda mm: mm.group(1) + "- ", indent + rest)
        items.append(("text", ln))
        i += 1

    items = [(k, t) for k, t in items if not (k == "text" and t.strip() and _PAGE_NUM.match(t))]
    counts = Counter(_norm_key(t) for k, t in items if _is_boiler_candidate(k, t))
    boiler = {key for key, c in counts.items() if c >= MIN_REPEATS and len(key) >= MIN_BOILER_LEN}
    seen: set[str] = set()
    kept: list[tuple[str, str]] = []
    for k, t in items:
        if _is_boiler_candidate(k, t):
            key = _norm_key(t)
            if key in boiler:
                if key in seen:
                    continue  # keep first occurrence only
                seen.add(key)
        kept.append((k, t))

    out: list[str] = []
    prev_kind, prev = None, None
    for k, t in kept:
        if k == "text" and t.strip() and prev_kind == "text" and t == prev:
            continue
        if not t.strip() and k != "code" and (not out or not out[-1].strip()):
            continue
        out.append(t)
        prev_kind, prev = k, t
    return "\n".join(out).strip("\n") + "\n"
