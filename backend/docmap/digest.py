"""Spreadsheet digest: stream a sheet once, keep stats + head rows instead of every row.

Uses openpyxl read_only streaming (xlsx) or csv, so huge files stay fast and low-memory.
"""
from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

DIGEST_ROWS = 200      # a sheet with more data rows than this gets a digest (mode auto)
HEAD_ROWS = 20         # rows shown in a digest
MAX_DISTINCT = 50_000  # stop tracking distinct text values beyond this
CELL_MAX = 60


@dataclass
class ColStats:
    name: str
    n: int = 0
    nums: int = 0
    dates: int = 0
    texts: int = 0
    total: float = 0.0
    lo: float | None = None
    hi: float | None = None
    dlo: object = None
    dhi: object = None
    counter: Counter = field(default_factory=Counter)
    overflow: bool = False

    def add(self, v) -> None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return
        self.n += 1
        if isinstance(v, bool):
            v = str(v)
        if isinstance(v, (int, float)):
            self.nums += 1
            self.total += v
            self.lo = v if self.lo is None or v < self.lo else self.lo
            self.hi = v if self.hi is None or v > self.hi else self.hi
        elif isinstance(v, (dt.datetime, dt.date)):
            self.dates += 1
            try:
                self.dlo = v if self.dlo is None or v < self.dlo else self.dlo
                self.dhi = v if self.dhi is None or v > self.dhi else self.dhi
            except TypeError:
                pass
        else:
            self.texts += 1
            if not self.overflow:
                self.counter[str(v).strip()] += 1
                if len(self.counter) > MAX_DISTINCT:
                    self.overflow = True

    @property
    def kind(self) -> str:
        if self.n == 0:
            return "empty"
        m = max(self.nums, self.dates, self.texts)
        if m == self.nums:
            return "number"
        return "date" if m == self.dates else "text"


@dataclass
class SheetInfo:
    name: str
    header: list[str] = field(default_factory=list)
    rows: int = 0                     # data rows (header and blank rows excluded)
    head: list[list] = field(default_factory=list)   # kept rows (all rows if not big)
    cols: list[ColStats] = field(default_factory=list)
    keep_all: bool = True
    digested: bool = False


def _fmt(v, nd: int = 4, cap: int | None = CELL_MAX) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.{nd}g}" if abs(v) < 1e15 else f"{v:.6g}"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.date().isoformat() if isinstance(v, dt.datetime) and v.time() == dt.time() else v.isoformat()
    s = str(v).replace("\r", " ").replace("\n", " ").replace("|", "/").strip()
    return s if cap is None or len(s) <= cap else s[: cap - 1] + "…"


def _scan(name: str, rows: Iterable[tuple], keep_limit: int) -> SheetInfo:
    info = SheetInfo(name)
    for raw in rows:
        if raw is None or all(v is None or (isinstance(v, str) and not v.strip()) for v in raw):
            continue
        row = list(raw)
        if not info.header:
            info.header = [_fmt(v, cap=None) or f"col{i + 1}" for i, v in enumerate(row)]
            info.cols = [ColStats(h) for h in info.header]
            continue
        info.rows += 1
        if len(row) > len(info.cols):  # ragged rows
            for i in range(len(info.cols), len(row)):
                info.header.append(f"col{i + 1}")
                info.cols.append(ColStats(f"col{i + 1}"))
        for c, v in zip(info.cols, row):
            c.add(v)
        if info.keep_all:
            if info.rows <= keep_limit:
                info.head.append(row)
            else:
                info.keep_all = False
    return info


def _xlsx_sheets(path: Path, only: list[str] | None = None) -> Iterator[tuple[str, Iterator[tuple]]]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            if only is None or ws.title in only:
                yield ws.title, ws.iter_rows(values_only=True)
    finally:
        wb.close()


def _csv_rows(path: Path) -> Iterator[tuple]:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        for row in csv.reader(f, dialect):
            yield tuple(_coerce(x) for x in row)


def _coerce(s: str):
    t = s.strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return s


def analyse_workbook(path: str | Path, digest_rows: int = DIGEST_ROWS) -> list[SheetInfo]:
    """One streaming pass. Sheets with <= digest_rows data rows keep every row."""
    path = Path(path)
    out = []
    if path.suffix.lower() == ".csv":
        out.append(_scan(path.stem, _csv_rows(path), digest_rows))
    else:
        for title, rows in _xlsx_sheets(path):
            out.append(_scan(title, rows, digest_rows))
    return out


def _table(header: list[str], rows: list[list], keep: list[int], cap: int | None = None) -> list[str]:
    L = ["|" + "|".join(_fmt(header[i], cap=cap) for i in keep) + "|", "|" + "|".join("-" for _ in keep) + "|"]
    for r in rows:
        L.append("|" + "|".join(_fmt(r[i], 12, cap) if i < len(r) else "" for i in keep) + "|")
    return L


def render_sheet(info: SheetInfo, file_name: str, as_digest: bool, head_rows: int = HEAD_ROWS) -> str:
    keep = [i for i, c in enumerate(info.cols) if c.n > 0]
    L = [f"## {info.name}", ""]
    if not as_digest:
        if keep:
            L += _table(info.header, info.head, keep)
        return "\n".join(L) + "\n"
    L.append(f"Sheet `{info.name}`: {info.rows} rows x {len(keep)} columns. Header: "
             + ", ".join(info.header[i] for i in keep))
    L += ["", "Columns:"]
    for i in keep:
        c = info.cols[i]
        k = c.kind
        if k == "number":
            mean = c.total / c.nums if c.nums else 0
            extra = f"min {_fmt(c.lo, 8)}, max {_fmt(c.hi, 8)}, mean {_fmt(mean, 8)}, sum {_fmt(c.total, 8)}"
        elif k == "date":
            extra = f"from {_fmt(c.dlo)} to {_fmt(c.dhi)}"
        else:
            d = f"{len(c.counter)}+" if c.overflow else str(len(c.counter))
            top = "; ".join(f"{_fmt(v)} ({n})" for v, n in c.counter.most_common(5))
            extra = f"{d} distinct; top: {top}"
        L.append(f"- {info.header[i]} [{k}, {c.n} filled]: {extra}")
    shown = min(head_rows, len(info.head))
    L.append("")
    L += _table(info.header, info.head[:shown], keep, CELL_MAX)
    L += ["", f"> Digest: {shown} of {info.rows} rows shown. Full data: {file_name}#{info.name}"]
    return "\n".join(L) + "\n"


def render_workbook(sheets: list[SheetInfo], file_name: str, mode: str = "auto",
                    digest_rows: int = DIGEST_ROWS, head_rows: int = HEAD_ROWS) -> tuple[str, list[str]]:
    """mode: 'auto' digests sheets above digest_rows, 'digest' digests all, 'full' none.
    Note: 'full' needs rows kept; analyse_workbook keeps only up to digest_rows (see convert)."""
    parts, digested = [], []
    for s in sheets:
        big = s.rows > digest_rows
        use = mode == "digest" or (mode == "auto" and big)
        if use:
            s.digested = True
            digested.append(s.name)
        parts.append(render_sheet(s, file_name, use, head_rows))
    return "\n".join(parts), digested


def full_stream_markdown(path: str | Path, only: list[str] | None = None, label: str = "") -> str:
    """Every row of every sheet as Markdown tables, streamed (low memory). Used when anydoc hits its
    resource limit on a huge workbook: Egi's rule is that rows are never cut silently."""
    path = Path(path)
    sheets = [(path.stem, _csv_rows(path))] if path.suffix.lower() == ".csv" else _xlsx_sheets(path, only)
    out: list[str] = []
    for title, rows in sheets:
        out += [f"## {title}{label}", ""]
        header = None
        for raw in rows:
            if raw is None or all(v is None or (isinstance(v, str) and not v.strip()) for v in raw):
                continue
            cells = [_fmt(v, 12, None) for v in raw]
            if header is None:
                header = [c or f"col{i + 1}" for i, c in enumerate(cells)]
                out += ["|" + "|".join(header) + "|", "|" + "|".join("-" for _ in header) + "|"]
                continue
            out.append("|" + "|".join(cells) + "|")
        out.append("")
    return "\n".join(out)
