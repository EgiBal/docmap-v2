"""Split slim Markdown into ~400-token chunks along headings."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .tokens import count

TARGET = 400
_HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def clean_title(doc_id: str) -> str:
    """Readable title from a file name: drop extension and a leading 'abc-01-' sort prefix."""
    stem = re.sub(r"\.(pdf|docx|xlsx|pptx)$", "", doc_id, flags=re.I)
    stem = re.sub(r"^[a-z]{2,5}-\d+-", "", stem, flags=re.I)
    return re.sub(r"[-_]+", " ", stem).strip()


@dataclass
class Chunk:
    doc_id: str
    idx: int
    heading_path: str
    text: str
    tokens: int


def _sections(md: str):
    """Yield (heading_path, lines) per heading section."""
    stack: list[tuple[int, str]] = []
    cur: list[str] = []
    path = ""
    in_fence = False
    for line in md.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        m = None if in_fence else _HEAD.match(line)
        if m:
            if any(x.strip() for x in cur):
                yield path, cur
            cur = []
            lvl = len(m.group(1))
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, m.group(2)))
            path = " > ".join(t for _, t in stack)
        else:
            cur.append(line)
    if any(x.strip() for x in cur):
        yield path, cur


def _split_lines(lines: list[str], target: int) -> list[list[str]]:
    """Greedy pack of lines into groups <= target tokens (a long line is cut by words)."""
    groups: list[list[str]] = []
    cur: list[str] = []
    n = 0
    for line in lines:
        t = count(line) + 1
        if t > target:  # a very long line (e.g. table blob): cut by words
            if cur:
                groups.append(cur)
                cur, n = [], 0
            piece: list[str] = []
            pn = 0
            for w in line.split(" "):
                wt = count(w) + 1
                if pn + wt > target and piece:
                    groups.append([" ".join(piece)])
                    piece, pn = [], 0
                piece.append(w)
                pn += wt
            if piece:
                cur, n = [" ".join(piece)], pn
            continue
        if n + t > target and cur:
            groups.append(cur)
            cur, n = [], 0
        cur.append(line)
        n += t
    if cur:
        groups.append(cur)
    return groups


def chunk_markdown(doc_id: str, md: str, target: int = TARGET, min_tokens: int = 40) -> list[Chunk]:
    raw: list[tuple[str, str]] = []
    for path, lines in _sections(md):
        for g in _split_lines(lines, target):
            text = "\n".join(g).strip()
            if text:
                raw.append((path, text))
    merged: list[tuple[str, str]] = []
    for path, text in raw:
        if merged and count(text) < min_tokens and count(merged[-1][1]) + count(text) <= target:
            p0, t0 = merged[-1]
            merged[-1] = (p0, t0 + "\n" + (f"{path}: " if path and path != p0 else "") + text)
        else:
            merged.append((path, text))
    return [Chunk(doc_id, i, p, t, count(t)) for i, (p, t) in enumerate(merged)]
