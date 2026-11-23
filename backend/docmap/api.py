"""FastAPI app: uv run uvicorn docmap.api:app --port 8000

Reads the SQLite store written by the pipeline; humans edit links with PATCH /api/links/{id}.
New optional fields (Document.token_count, Document.size_warning) are read with getattr.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import convert, store
from .store import Chunk, Document, Link, Run, Topic
from .paths import ROOT

def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name) or default)


UPLOAD_DIR = _env_path("DOCMAP_UPLOAD_DIR", str(ROOT / "data" / "uploads"))
MD_DIR = _env_path("DOCMAP_MD_DIR", str(ROOT / "data" / "md"))
CORPUS_DIR = _env_path("DOCMAP_CORPUS_DIR", str(ROOT / "corpus" / "raw"))
EXPORT_DIR = _env_path("DOCMAP_EXPORT_DIR", str(ROOT / "data" / "export"))
TOKEN_CACHE = ROOT / "data" / "cache" / "doc_tokens.json"
PACK_LIMIT = 128_000            # export warns above this (same as export.TOKEN_LIMIT)
LARGE_TOKENS = 100_000          # warn above this many tokens (typical LLM context 128k / 200k)
MAX_UPLOAD_MB = int(os.environ.get("DOCMAP_MAX_UPLOAD_MB") or 100)
MAX_NAME = 100                  # file name stem length kept on upload
ALLOWED_EXTS = convert.ALLOWED_EXTS
HEADER = "x-docmap"             # custom header on every write request: blocks drive-by requests from web pages

log = logging.getLogger("docmap.api")
app = FastAPI(title="DocMap API")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_header(request: Request, call_next):
    """A custom header forces a CORS preflight, so a random web page cannot POST/PATCH to localhost."""
    if request.method in ("POST", "PATCH", "PUT", "DELETE") and request.headers.get(HEADER) != "1":
        return JSONResponse({"detail": f"missing {HEADER}: 1 header"}, status_code=403)
    if request.url.path == "/api/upload" and int(request.headers.get("content-length") or 0) > 20 * MAX_UPLOAD_MB * 1024 * 1024:
        return JSONResponse({"detail": "upload request is too large"}, status_code=413)
    return await call_next(request)


_cold_runs = int(os.environ.get("DOCMAP_COLD_RUNS") or 0)   # first N runs ignore cached LLM answers (real NIM calls; used by the e2e proof)
_state: dict = {"engine": None, "db": _env_path("DOCMAP_DB", str(store.DB_PATH))}
_preview_cache: dict = {}


def configure(db: Path | str | None = None, upload_dir: Path | str | None = None,
              md_dir: Path | str | None = None, corpus_dir: Path | str | None = None,
              export_dir: Path | str | None = None) -> None:
    """Point the app at another DB / folders (used by tests)."""
    global UPLOAD_DIR, MD_DIR, CORPUS_DIR, EXPORT_DIR
    if db is not None:
        _state["db"], _state["engine"] = db, None
    if upload_dir is not None:
        UPLOAD_DIR = Path(upload_dir)
    if md_dir is not None:
        MD_DIR = Path(md_dir)
    if corpus_dir is not None:
        CORPUS_DIR = Path(corpus_dir)
    if export_dir is not None:
        EXPORT_DIR = Path(export_dir)
    _preview_cache.clear()


def eng():
    if _state["engine"] is None:
        _state["engine"] = store.get_engine(_state["db"])
    return _state["engine"]


# ---------------------------------------------------------------- helpers
def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _naive_map() -> dict[str, int]:
    """doc id -> naive-dump tokens (from the T05 token cache; best effort)."""
    try:
        raw = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k.split("|")[0]: int(v.get("naive", 0)) for k, v in raw.items()}


def _json(s: str, default):
    try:
        return json.loads(s)
    except Exception:
        return default


def _tokens(d: Document) -> int:
    return int(getattr(d, "token_count", 0) or d.tokens or 0)


def _size_warning(d: Document) -> Optional[str]:
    w = getattr(d, "size_warning", None)
    if w:
        return str(w)
    t = _tokens(d)
    if t >= LARGE_TOKENS:
        return f"about {t:,} tokens, may be too large for an LLM context window (128k / 200k)"
    return None


def _doc_status(d: Document) -> str:
    return d.status if d.status in ("ok", "needs_ocr", "digest", "error", "unsupported") else (
        "ok" if d.status == "fallback" else d.status)


_KINDS = [("ocr", re.compile(r"\bocr\b|scanned", re.I)), ("hidden", re.compile(r"hidden sheet", re.I)),
          ("encrypted", re.compile(r"encrypt|password", re.I)), ("unsupported", re.compile(r"unsupported", re.I))]


def _doc_warnings(d: Document) -> list[dict]:
    """Per-document warnings for the UI: {kind, text}. kind: ocr | hidden | encrypted | unsupported | size | other."""
    out: list[dict] = []
    if d.status == "unsupported" and not (d.note or "").strip():
        out.append({"kind": "unsupported", "text": "unsupported file type"})
    for part in [p.strip() for p in (d.note or "").split("; ") if p.strip()]:
        kind = next((k for k, rx in _KINDS if rx.search(part)), "other")
        out.append({"kind": kind, "text": part})
    sw = _size_warning(d)
    if sw:
        out.append({"kind": "size", "text": sw})
    return out


def _link_out(l: Link, topics: dict[int, Topic]) -> dict:
    t = topics.get(l.topic_id)
    return {"id": l.id, "doc_id": l.doc_id, "topic_id": l.topic_id, "topic_name": t.name if t else "?",
            "score": l.score, "confidence": l.confidence, "status": l.status, "source": l.source,
            "moved_to": l.moved_to, "reviewed_at": _iso(l.reviewed_at), "evidence": _json(l.evidence, []),
            "disagreement": bool(getattr(l, "disagreement", False)),
            "content_changed": bool(getattr(l, "content_changed", False))}


def _topics(s: Session, active_only=True) -> dict[int, Topic]:
    q = select(Topic)
    if active_only:
        q = q.where(Topic.active == True)  # noqa: E712
    return {t.id: t for t in s.exec(q).all()}


def _live_links(s: Session) -> list[Link]:
    """Links whose topic is active and which are not the 'moved away' marker (kept for history)."""
    ids = set(_topics(s))
    return [l for l in s.exec(select(Link)).all() if l.topic_id in ids]


def _pack_stats(docs: list[Document], links: list[Link], library_tokens: int) -> dict:
    """Topic-pack saving: median tokens of one theme's pack (every doc linked to it, not rejected or moved)
    against the whole library as a plain-text dump. This is the main token win of routing."""
    import statistics
    tok = {d.id: _tokens(d) for d in docs}
    per: dict[int, set[str]] = {}
    for l in links:
        if l.status not in ("rejected", "moved") and l.doc_id in tok:
            per.setdefault(l.topic_id, set()).add(l.doc_id)
    sizes = sorted(sum(tok[i] for i in ids) for ids in per.values())
    if not sizes or not library_tokens:
        return {"n_topics": len(sizes), "median_tokens": 0, "largest_tokens": 0, "median_saved_pct": 0.0,
                "library_tokens": library_tokens}
    med = statistics.median(sizes)
    return {"n_topics": len(sizes), "median_tokens": int(med), "largest_tokens": sizes[-1],
            "median_saved_pct": round(100 * (1 - med / library_tokens), 1), "library_tokens": library_tokens}


# ---------------------------------------------------------------- read endpoints
@app.get("/api/metrics")
def metrics():
    with Session(eng()) as s:
        docs = s.exec(select(Document)).all()
        links = _live_links(s)
        topics = _topics(s)
        by_status: dict[str, int] = {}
        for l in links:
            by_status[l.status] = by_status.get(l.status, 0) + 1
        naive = _naive_map()
        slim_total = sum(_tokens(d) for d in docs)
        naive_total = sum(naive.get(d.id, _tokens(d)) for d in docs)
        saved = round(100 * (1 - slim_total / naive_total), 1) if naive_total else 0.0
        pack = _pack_stats(docs, links, naive_total)
        run =s.exec(select(Run).order_by(Run.id.desc())).first()
        return {
            "docs": len(docs), "topics": len(topics), "links": by_status, "links_total": len(links),
            "tokens": {"naive": naive_total, "slim": slim_total, "saved_pct": saved,
                       "naive_known": any(d.id in naive for d in docs)},   # baseline exists only after docmap.report
            "pack": pack,
            "open_reviews": by_status.get("proposed", 0),
            "size_warnings": sum(1 for d in docs if _size_warning(d)),
            "needs_ocr": sum(1 for d in docs if d.status == "needs_ocr"),
            "last_run": None if run is None else {"id": run.id, "started_at": _iso(run.started_at),
                                                  "preset": run.preset, "n_docs": run.n_docs,
                                                  "n_topics": run.n_topics, "timings": _json(run.timings, {})},
        }


@app.get("/api/topics")
def list_topics():
    with Session(eng()) as s:
        topics = _topics(s)
        counts: dict[int, int] = {}
        for l in _live_links(s):
            if l.status in ("proposed", "accepted"):
                counts[l.topic_id] = counts.get(l.topic_id, 0) + 1
        return [{"id": t.id, "name": t.name, "description": t.description, "synonyms": _json(t.synonyms, []),
                 "doc_count": counts.get(t.id, 0)} for t in topics.values()]


def _top_link(links: list[Link]) -> Optional[Link]:
    live = [l for l in links if l.status in ("proposed", "accepted")]
    if not live:
        return None
    return max(live, key=lambda l: (l.status == "accepted", l.confidence))


@app.get("/api/documents")
def list_documents():
    with Session(eng()) as s:
        topics = _topics(s)
        per_doc: dict[str, list[Link]] = {}
        for l in _live_links(s):
            per_doc.setdefault(l.doc_id, []).append(l)
        out = []
        naive = _naive_map()
        for d in s.exec(select(Document).order_by(Document.id)).all():
            top = _top_link(per_doc.get(d.id, []))
            out.append({"id": d.id, "format": d.format, "status": _doc_status(d), "token_count": _tokens(d),
                        "naive_tokens": naive.get(d.id),
                        "size_warning": _size_warning(d), "note": d.note, "warnings": _doc_warnings(d),
                        "top_topic": None if top is None else {"id": top.topic_id, "name": topics[top.topic_id].name,
                                                               "confidence": top.confidence, "status": top.status,
                                                               "link_id": top.id}})
        return out


def _preview_text(f, limit: int) -> tuple[str, bool]:
    """First `limit` characters, cut at a line break so a table row is not split."""
    md = f.read(limit)
    truncated = bool(f.read(1))
    if truncated and "\n" in md:
        md = md[: md.rindex("\n")]
    return md, truncated


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, limit: int = 60_000):
    limit = max(1_000, min(limit, 400_000))
    with Session(eng()) as s:
        d = s.get(Document, doc_id)
        if d is None:
            raise HTTPException(404, "document not found")
        topics = _topics(s)
        links = [_link_out(l, topics) for l in _live_links(s) if l.doc_id == doc_id]
        md_path = MD_DIR / f"{doc_id}.md"
        md, truncated = "", False
        total_chars = 0
        if md_path.exists():
            total_chars = md_path.stat().st_size   # bytes: close enough for a label
            with md_path.open("r", encoding="utf-8", errors="replace") as f:
                md, truncated = _preview_text(f, limit)
        elif (chunks := s.exec(select(Chunk).where(Chunk.doc_id == doc_id).order_by(Chunk.idx)).all()):
            md = "\n\n".join((f"## {c.heading_path}\n\n" if c.heading_path else "") + c.text for c in chunks)
        dw = _doc_warnings(d)
        if d.status == "needs_ocr" and not any(w["kind"] == "ocr" for w in dw):
            dw.append({"kind": "ocr", "text": "scanned document: needs OCR before it can be converted"})
        warnings = [w["text"] for w in dw if w["kind"] != "size"]
        naive = _naive_map().get(doc_id, _tokens(d))
        return {"id": d.id, "format": d.format, "status": _doc_status(d), "markdown": md, "truncated": truncated,
                "preview_chars": len(md), "total_bytes": total_chars, "doc_warnings": dw,
                "tokens": {"naive": naive, "slim": _tokens(d),
                           "saved_pct": round(100 * (1 - _tokens(d) / naive), 1) if naive else 0.0},
                "size_warning": _size_warning(d), "warnings": warnings, "links": links}


@app.get("/api/graph")
def graph():
    """React Flow shape: nodes {id,type,data}, edges {id,source,target,data}. Positions are set client-side."""
    with Session(eng()) as s:
        topics = _topics(s)
        docs = s.exec(select(Document)).all()
        links = _live_links(s)
        nodes = [{"id": f"t{t.id}", "type": "topic", "data": {"topic_id": t.id, "label": t.name,
                                                               "description": t.description}}
                 for t in topics.values()]
        nodes += [{"id": f"d{d.id}", "type": "doc", "data": {"doc_id": d.id, "label": d.id, "format": d.format,
                                                              "status": _doc_status(d),
                                                              "warn": len(_doc_warnings(d))}} for d in docs]
        edges = [{"id": f"l{l.id}", "source": f"d{l.doc_id}", "target": f"t{l.topic_id}",
                  "data": {"link_id": l.id, "status": l.status, "confidence": l.confidence, "source": l.source,
                           "doc_id": l.doc_id, "topic_id": l.topic_id}}
                 for l in links if l.status != "moved"]
        return {"nodes": nodes, "edges": edges}


@app.get("/api/review")
def review_queue():
    with Session(eng()) as s:
        topics = _topics(s)
        sugg = _load_suggestions()
        out = [_link_out(l, topics) for l in _live_links(s) if l.status == "proposed"]
        for x in out:
            tid = sugg.get(x["id"])
            x["suggestion"] = ({"topic_id": tid, "topic_name": topics[tid].name}
                               if tid in topics and tid != x["topic_id"] else None)
        out.sort(key=lambda x: (not x["disagreement"], x["confidence"]))
        return out


class LinkAction(BaseModel):
    action: str                   # accept | reject | move
    topic_id: Optional[int] = None


@app.patch("/api/links/{link_id}")
def patch_link(link_id: int, body: LinkAction):
    if body.action not in ("accept", "reject", "move"):
        raise HTTPException(422, "action must be accept, reject or move")
    if _job["state"] == "running":
        raise HTTPException(409, "a run is in progress; try again when it has finished")
    with Session(eng()) as s:
        l = s.get(Link, link_id)
        if l is None:
            raise HTTPException(404, "link not found")
        doc_id, topic_id = l.doc_id, l.topic_id
        if body.action == "move":
            if body.topic_id is None or body.topic_id not in _topics(s):
                raise HTTPException(422, "move needs a valid active topic_id")
            if body.topic_id == topic_id:
                raise HTTPException(422, "target topic is the current topic")
    status = {"accept": "accepted", "reject": "rejected", "move": "moved"}[body.action]
    store.human_set_link(eng(), doc_id, topic_id, status, moved_to=body.topic_id if body.action == "move" else None)
    with Session(eng()) as s:
        topics = _topics(s)
        res = [_link_out(x, topics) for x in s.exec(select(Link).where(Link.doc_id == doc_id)).all()
               if x.topic_id in (topic_id, body.topic_id)]
    return {"link": next(x for x in res if x["id"] == link_id), "affected": res}


# ---------------------------------------------------------------- export
def _db_stamp() -> tuple:
    try:
        st = Path(_state["db"]).stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def _md_stamp() -> int:
    try:
        return (MD_DIR / "_meta.json").stat().st_mtime_ns
    except OSError:
        return 0


def _do_export(fmt: str, digest: bool, accepted_only: bool, out_dir: Path, dry_run: bool = False):
    from .export import export_pack
    if fmt not in ("zip", "folder"):
        raise HTTPException(422, "fmt must be zip or folder")
    return export_pack(_state["db"], out_dir, statuses=("accepted",) if accepted_only else ("accepted", "proposed"),
                       include_secondary=True, digest=digest, fmt=fmt, md_dir=MD_DIR,
                       raw_dir=[UPLOAD_DIR, CORPUS_DIR], dry_run=dry_run)


@app.get("/api/export/preview")
def export_preview(digest: bool = False, accepted_only: bool = False):
    """Per-topic token counts and warnings for the pack. Token counts only: nothing is written, and the
    answer is cached until the database or the converted Markdown changes."""
    key = (_db_stamp(), _md_stamp(), digest, accepted_only, str(MD_DIR))
    hit = _preview_cache.get(key)
    if hit is None:
        res = _do_export("folder", digest, accepted_only, Path("."), dry_run=True)
        topics = [{"file": f, "tokens": t, "too_large": t > PACK_LIMIT} for f, t in res.per_topic_tokens.items()]
        hit = {"topics": topics, "warnings": res.warnings, "files": res.files, "digest": digest,
               "accepted_only": accepted_only, "limit": PACK_LIMIT}
        _preview_cache.clear()
        _preview_cache[key] = hit
    return hit


@app.get("/api/export")
def export(background: BackgroundTasks, fmt: str = "zip", digest: bool = False, accepted_only: bool = False):
    """Download the context pack as a zip (built in a temp folder that is removed afterwards)."""
    import shutil
    import tempfile
    if fmt != "zip":
        raise HTTPException(422, "fmt must be zip here; POST /api/export/folder writes a folder")
    tmp = Path(tempfile.mkdtemp(prefix="docmap-exp-"))
    try:
        res = _do_export("zip", digest, accepted_only, tmp)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    background.add_task(shutil.rmtree, tmp, True)
    zp = Path(res.paths[0])
    return FileResponse(zp, filename=zp.name, media_type="application/zip",
                        headers={"X-Docmap-Warnings": str(len(res.warnings)),
                                 "Access-Control-Expose-Headers": "X-Docmap-Warnings, Content-Disposition"})


@app.post("/api/export/folder")
def export_folder(digest: bool = False, accepted_only: bool = False):
    """Write the pack into the export folder. Files a previous export wrote there are replaced."""
    res = _do_export("folder", digest, accepted_only, EXPORT_DIR)
    return {"folder": str(EXPORT_DIR), "files": res.files, "per_topic_tokens": res.per_topic_tokens,
            "warnings": res.warnings}


# ---------------------------------------------------------------- upload + process
class _TooLarge(Exception):
    pass


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _safe_name(raw: str) -> str:
    """Plain file name: no path, only letters/digits/._- and space, stem capped, extension kept (lower case)."""
    name = Path((raw or "file").replace("\\", "/")).name
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^\w.\- ]", "_", stem).strip(" .")[:MAX_NAME].strip(" .") or "file"
    ext = re.sub(r"[^\w.]", "_", ext).lower()[:12]
    if stem.upper() in _RESERVED:
        stem = "_" + stem
    return stem + ext


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _target(name: str, digest: str) -> tuple[Path, bool]:
    """(path, already_there). Same name + same bytes: reuse. Same name + other bytes: 'name (2).ext'."""
    stem, ext = os.path.splitext(name)
    for n in range(1, 1000):
        p = UPLOAD_DIR / (name if n == 1 else f"{stem} ({n}){ext}")
        if not p.exists():
            return p, False
        if _sha(p) == digest:
            return p, True
    raise OSError("too many files with the same name")


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Stream each file to disk. A bad file is reported in `errors` and does not stop the others."""
    cap = MAX_UPLOAD_MB * 1024 * 1024
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved, unchanged, skipped, errors = [], [], [], []
    for f in files:
        name = _safe_name(f.filename or "")
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            skipped.append(name)
            errors.append({"name": name, "reason": f"unsupported file type {ext or '(no extension)'}: allowed are "
                           + ", ".join(e.lstrip(".") for e in ALLOWED_EXTS)})
            continue
        tmp = UPLOAD_DIR / f".upload-{os.getpid()}-{time.time_ns()}.part"
        try:
            size, h = 0, hashlib.sha256()
            with tmp.open("wb") as out:
                while chunk := await f.read(1 << 20):
                    size += len(chunk)
                    if size > cap:
                        raise _TooLarge()
                    h.update(chunk)
                    out.write(chunk)
            if size == 0:
                skipped.append(name)
                errors.append({"name": name, "reason": "the file is empty"})
                continue
            dest, same = _target(name, h.hexdigest())
            if same:
                unchanged.append(dest.name)
            else:
                tmp.replace(dest)
                saved.append(dest.name)
        except _TooLarge:
            skipped.append(name)
            errors.append({"name": name, "reason": f"file is larger than {MAX_UPLOAD_MB} MB (DOCMAP_MAX_UPLOAD_MB)"})
        except Exception as e:  # noqa: BLE001 - one bad file must not abort the batch
            log.warning("upload of %r failed: %s: %s", name, type(e).__name__, e)
            skipped.append(name)
            errors.append({"name": name, "reason": "could not save this file"})
        finally:
            tmp.unlink(missing_ok=True)
    return {"saved": saved, "unchanged": unchanged, "skipped": skipped, "errors": errors, "dir": str(UPLOAD_DIR)}


_job: dict = {"state": "idle", "kind": "", "step": "", "done": 0, "total": 0, "pct": 0, "message": "", "started": None, "finished": None, "result": None, "stage_times": {}}
_job_lock = threading.Lock()
# (stage, start %, end %): rough share of the wall time of a real run (profile = one LLM call per document)
STAGES = [("convert", 0, 8), ("chunk", 8, 12), ("embed", 12, 30), ("profile", 30, 85), ("induce", 85, 95), ("save", 95, 100)]
_STAGE_PCT = {n: (a, b) for n, a, b in STAGES}


def _progress(stage: str, done: int, total: int):
    a, b = _STAGE_PCT.get(stage, (0, 95))
    frac = min(1.0, done / total) if total else 1.0
    with _job_lock:
        if _job["state"] == "running":
            st = _job["stage_times"].setdefault(stage, {"first": round(time.time() - _job["started"], 2), "total": total})
            st["last"], st["done"] = round(time.time() - _job["started"], 2), done
            _job.update(step=stage, done=done, total=total, pct=min(99, int(round(a + (b - a) * frac))))


def _run_job(preset: Optional[str], source: Path):
    def upd(**kw):
        with _job_lock:
            _job.update(kw)

    try:
        from .pipeline import run_pipeline
        global _cold_runs
        cold = _cold_runs > 0
        _cold_runs = max(0, _cold_runs - 1)
        out = run_pipeline(source, preset or _settings()["preset"], _state["db"], verbose=False,
                           on_progress=_progress, _md_dir=MD_DIR, cold=cold)
        _state["engine"] = None
        _preview_cache.clear()
        upd(state="done", step="done", pct=100, message="finished", finished=time.time(),
            result={"timings": out.get("timings"), "topics": out.get("topics"), "n_chunks": out.get("n_chunks")})
    except Exception as e:  # noqa: BLE001
        log.exception("pipeline failed")
        step = _job.get("step") or "pipeline"
        upd(state="error", message=f"Processing failed in the {step} step ({type(e).__name__}). "
                                   "Details are in the server log.", finished=time.time())

class ProcessBody(BaseModel):
    preset: Optional[str] = None
    source: Optional[str] = None   # a folder inside the uploads folder or the corpus folder; default = uploads
    sample: bool = False           # true = the configured corpus folder (DOCMAP_CORPUS_DIR)


def _resolve_source(body: ProcessBody) -> Path:
    if body.sample:
        return CORPUS_DIR
    if not body.source:
        return UPLOAD_DIR
    try:
        p = Path(body.source).resolve()
    except (OSError, ValueError):
        raise HTTPException(400, "invalid source")
    for allowed in (UPLOAD_DIR, CORPUS_DIR):
        a = allowed.resolve()
        if p == a or p.is_relative_to(a):
            return p
    raise HTTPException(400, "source must be the uploads folder or the corpus folder")


@app.post("/api/process")
def process(body: ProcessBody | None = None):
    body = body or ProcessBody()
    source = _resolve_source(body)
    if not source.is_dir() or not any(p for p in source.iterdir() if not p.name.startswith(".")):
        raise HTTPException(400, "nothing to process in that folder")
    with _job_lock:
        if _job["state"] == "running":
            raise HTTPException(409, "a run is already in progress")
        _job.update(state="running", kind="process", step="convert", done=0, total=0, pct=0, message="", started=time.time(), finished=None, result=None, stage_times={})
    threading.Thread(target=_run_job, args=(body.preset, source), daemon=True).start()
    return {"state": "running"}


def _run_convert(source: Path):
    """Convert only: every file in the folder becomes Markdown in MD_DIR. No model is called."""
    def prog(stage, done, total):
        with _job_lock:
            _job.update(step="convert", done=done, total=total, pct=min(99, int(100 * done / total)) if total else 0)
    try:
        from .pipeline import load_docs
        docs = load_docs(source, False, MD_DIR, prog)
        bad = [d["id"] for d in docs if not d["md"]]
        with _job_lock:
            _job.update(state="done", step="done", pct=100, finished=time.time(),
                        message=f"converted {len(docs) - len(bad)} of {len(docs)} files"
                                + (f"; not converted: {', '.join(bad)}" if bad else ""),
                        result={"converted": len(docs) - len(bad), "failed": bad})
    except Exception as e:  # noqa: BLE001
        log.exception("convert failed")
        with _job_lock:
            _job.update(state="error", message=f"Conversion failed ({type(e).__name__}). Details are in the server log.",
                        finished=time.time())


@app.post("/api/convert")
def convert_only(body: ProcessBody | None = None):
    """Markdown only (no topics, no model calls). Process later reuses these files, so nothing is converted twice."""
    body = body or ProcessBody()
    source = _resolve_source(body)
    if not source.is_dir() or not any(p for p in source.iterdir() if not p.name.startswith(".")):
        raise HTTPException(400, "nothing to convert: upload files first")
    with _job_lock:
        if _job["state"] == "running":
            raise HTTPException(409, "a run is already in progress")
        _job.update(state="running", kind="convert", step="convert", done=0, total=0, pct=0, message="",
                    started=time.time(), finished=None, result=None, stage_times={})
    threading.Thread(target=_run_convert, args=(source,), daemon=True).start()
    return {"state": "running"}


def _status() -> dict:
    with _job_lock:
        j = dict(_job)
    j["elapsed"] = round((j["finished"] or time.time()) - j["started"], 1) if j["started"] else 0
    return j


@app.get("/api/process/status")
def process_status():
    return _status()


# ---------------------------------------------------------------- re-score from reviews
def _sugg_path() -> Path:
    return Path(str(_state["db"]) + ".suggestions.json")


def _load_suggestions() -> dict[int, int]:
    try:
        return {int(k): int(v) for k, v in json.loads(_sugg_path().read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


class RescoreBody(BaseModel):
    dry_run: bool = False
    preset: Optional[str] = None


@app.post("/api/rescore")
def rescore(body: RescoreBody | None = None):
    """Re-score the open AI links from the human reviews (feedback.rescore). Confidence changes are written;
    moves are only suggested (shown as hints on the review page), never applied."""
    body = body or RescoreBody()
    if _job["state"] == "running":
        raise HTTPException(409, "a run is in progress; try again when it has finished")
    from . import feedback
    try:
        res = feedback.rescore(_state["db"], preset=body.preset or _settings()["preset"], dry_run=body.dry_run)
    except Exception as e:  # noqa: BLE001
        log.exception("rescore failed")
        raise HTTPException(500, f"Re-score failed ({type(e).__name__}). Details are in the server log.")
    if not body.dry_run:
        _sugg_path().write_text(json.dumps({str(k): v for k, v in res.suggested_topic_id.items()}), encoding="utf-8")
    _preview_cache.clear()
    with Session(eng()) as s:
        names = {t.id: t.name for t in s.exec(select(Topic)).all()}
    return {"dry_run": body.dry_run, "n_open": res.n_open, "n_reviews": res.n_reviews, "changed": len(res.changed),
            "suggestions": {str(k): {"topic_id": v, "topic_name": names.get(v, "?")}
                            for k, v in res.suggested_topic_id.items()},
            "message": f"Re-scored {res.n_open} open links using your {res.n_reviews} reviews"}






# ---------------------------------------------------------------- settings: which model does the AI steps
SETTINGS_FILE = _env_path("DOCMAP_SETTINGS", str(ROOT / "data" / "settings.json"))
OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL") or "http://localhost:11434"
KEY_VARS = ("LLM_API_KEY", "EMBED_API_KEY", "RERANK_API_KEY")


def _settings() -> dict:
    try:
        s = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    if s.get("preset") not in ("nim", "local"):
        s["preset"] = os.environ.get("DOCMAP_PRESET") or "nim"
    return s


def _cfg(preset: str) -> dict:
    from .llm import load_config
    return load_config(preset)


def _local_models() -> dict:
    c = _cfg("local")
    return {"llm": c["LLM_MODEL"], "embed": c["EMBED_MODEL"]}


@app.get("/api/settings")
def get_settings():
    s = _settings()
    nim = _cfg("nim")
    return {"preset": s["preset"],
            "nim": {"key_set": bool((nim.get("LLM_API_KEY") or "").strip()),
                    "llm": nim["LLM_MODEL"], "embed": nim["EMBED_MODEL"]},
            "local": {"url": OLLAMA_URL, **_local_models()},
            "folders": {"uploads": str(UPLOAD_DIR), "markdown": str(MD_DIR), "export": str(EXPORT_DIR)}}


class SettingsBody(BaseModel):
    preset: str


@app.put("/api/settings")
def put_settings(body: SettingsBody):
    if body.preset not in ("nim", "local"):
        raise HTTPException(422, "preset must be nim or local")
    if _job["state"] == "running":
        raise HTTPException(409, "a run is in progress; try again when it has finished")
    s = _settings()
    s["preset"] = body.preset
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=1), encoding="utf-8")
    return get_settings()


class KeyBody(BaseModel):
    key: str


@app.post("/api/settings/nim-key")
def set_nim_key(body: KeyBody):
    """Save an NVIDIA API key into backend/.env (all three roles). The key is never sent back."""
    from .llm import ENV_FILE
    key = body.key.strip()
    if not re.fullmatch(r"nvapi-[A-Za-z0-9_\-]{20,200}", key):
        raise HTTPException(422, "this does not look like an NVIDIA key (it starts with nvapi-)")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    done: set[str] = set()
    for i, ln in enumerate(lines):
        name = ln.split("=", 1)[0].strip()
        if name in KEY_VARS and not ln.lstrip().startswith("#"):
            lines[i] = f"{name}={key}"
            done.add(name)
    lines += [f"{v}={key}" for v in KEY_VARS if v not in done]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return get_settings()


def _has_model(installed: list[str], want: str) -> bool:
    w = want if ":" in want else want + ":latest"
    return any(m == want or m == w for m in installed)


@app.get("/api/settings/check")
def check_settings(preset: str = "local"):
    """Live check. local: is Ollama running, are the two models pulled. nim: does the key work (1 tiny embed call)."""
    import httpx
    if preset == "local":
        want = _local_models()
        try:
            r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.5)
            r.raise_for_status()
            installed = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return {"preset": "local", "ok": False, "running": False, "installed": [],
                    "missing": list(want.values()), "message": "Ollama is not running (or not installed)."}
        missing = [m for m in want.values() if not _has_model(installed, m)]
        return {"preset": "local", "ok": not missing, "running": True, "installed": installed, "missing": missing,
                "message": "Ready." if not missing else "Ollama runs, but these models are missing: " + ", ".join(missing)}
    if preset != "nim":
        raise HTTPException(422, "preset must be nim or local")
    c = _cfg("nim")
    key = (c.get("EMBED_API_KEY") or c.get("LLM_API_KEY") or "").strip()
    if not key:
        return {"preset": "nim", "ok": False, "message": "No NVIDIA API key is saved yet."}
    body = {"model": c["EMBED_MODEL"], "input": ["ping"], "encoding_format": "float"}
    if c.get("EMBED_INPUT_TYPE") == "1":
        body["input_type"] = "query"
    try:
        r = httpx.post(f"{c['EMBED_BASE_URL']}/embeddings", json=body, timeout=20,
                       headers={"Authorization": f"Bearer {key}"})
    except Exception as e:  # noqa: BLE001
        return {"preset": "nim", "ok": False, "message": f"Cannot reach NVIDIA NIM ({type(e).__name__})."}
    if r.status_code in (401, 403):
        return {"preset": "nim", "ok": False, "message": "NVIDIA refused the key (401/403). Check the key."}
    if r.status_code >= 400:
        return {"preset": "nim", "ok": False, "message": f"NVIDIA NIM answered HTTP {r.status_code}."}
    return {"preset": "nim", "ok": True, "message": "Ready. The key works."}


# ---------------------------------------------------------------- converted files: list, download, open folder
def _md_file(name: str) -> Path:
    p = (MD_DIR / name).resolve()
    if p.parent != MD_DIR.resolve() or p.suffix != ".md" or not p.is_file():
        raise HTTPException(404, "file not found")
    return p


@app.get("/api/files")
def list_files():
    """Every converted Markdown file on disk (from Convert or Process), newest first."""
    if not MD_DIR.is_dir():
        return {"folder": str(MD_DIR), "files": []}
    out = []
    for p in MD_DIR.glob("*.md"):
        st = p.stat()
        out.append({"name": p.name, "source": p.name[:-3], "bytes": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
    out.sort(key=lambda f: f["modified"], reverse=True)
    return {"folder": str(MD_DIR), "files": out}


@app.get("/api/files/all.zip")
def download_all(background: BackgroundTasks):
    import tempfile
    import zipfile
    files = sorted(MD_DIR.glob("*.md")) if MD_DIR.is_dir() else []
    if not files:
        raise HTTPException(404, "no converted files yet")
    fd, tmp = tempfile.mkstemp(prefix="docmap-md-", suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)
    background.add_task(os.remove, tmp)
    return FileResponse(tmp, filename="docmap-markdown.zip", media_type="application/zip")


@app.get("/api/files/{name}")
def download_file(name: str):
    p = _md_file(name)
    return FileResponse(p, filename=p.name, media_type="text/markdown; charset=utf-8")


class FolderBody(BaseModel):
    which: str   # markdown | export | uploads


@app.post("/api/open-folder")
def open_folder(body: FolderBody):
    """Open the folder in Windows Explorer (the app runs on this PC)."""
    folder = {"markdown": MD_DIR, "export": EXPORT_DIR, "uploads": UPLOAD_DIR}.get(body.which)
    if folder is None:
        raise HTTPException(422, "which must be markdown, export or uploads")
    folder.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(str(folder))  # noqa: S606 - fixed allowlisted folder
        return {"opened": str(folder)}
    return {"opened": None, "folder": str(folder)}
