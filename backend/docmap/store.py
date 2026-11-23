"""SQLite store (sqlmodel). Rule: a re-run never overwrites a link with source=human,
and topics are matched to the previous run's topics by embedding similarity so ids stay stable."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.optimize import linear_sum_assignment
from sqlalchemy import Column, LargeBinary, UniqueConstraint
from sqlmodel import Field, Session, SQLModel, create_engine, select
from .paths import ROOT

DB_PATH = ROOT / "data" / "docmap.db"
MATCH_SIM = 0.75      # new topic keeps an old topic's id if embeddings are at least this similar


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    id: str = Field(primary_key=True)             # file name
    format: str = ""
    status: str = "ok"                            # ok | needs_ocr | error | fallback
    tokens: int = 0                               # slim MD tokens
    note: str = ""
    updated_at: datetime = Field(default_factory=_now)
    token_count: int = 0                          # slim MD tokens, o200k, of the COMPLETE markdown
    size_warning: Optional[str] = None            # text when the MD is larger than typical LLM context windows
    content_hash: str = ""                        # sha256 of the raw source file the MD was made from


class Chunk(SQLModel, table=True):
    id: str = Field(primary_key=True)             # "<doc_id>#<idx>"
    doc_id: str = Field(index=True)
    idx: int = 0
    heading_path: str = ""
    text: str = ""
    tokens: int = 0


class Topic(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    synonyms: str = "[]"                          # JSON list
    embedding: bytes = Field(default=b"", sa_column=Column(LargeBinary))
    centroid: bytes = Field(default=b"", sa_column=Column(LargeBinary))
    active: bool = True
    name_locked: bool = False                     # a human renamed it: keep the name on re-run
    run_id: int = 0
    created_at: datetime = Field(default_factory=_now)


class Link(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("doc_id", "topic_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    doc_id: str = Field(index=True)
    topic_id: int = Field(index=True)
    score: float = 0.0
    confidence: float = 0.0
    status: str = "proposed"                      # proposed | accepted | rejected | moved
    moved_to: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    source: str = "ai"                            # ai | human
    evidence: str = "[]"                          # JSON
    role: str = "primary"                         # primary | secondary | alternative
    disagreement: bool = False                    # LLM and embedding disagreed: review-queue priority
    content_changed: bool = False                 # human link whose document changed after the review


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=_now)
    preset: str = ""
    params: str = "{}"
    timings: str = "{}"
    n_docs: int = 0
    n_topics: int = 0


def vec_to_bytes(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def bytes_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def get_engine(path: Path | str = DB_PATH):
    p = str(path)
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    # timeout = sqlite busy_timeout in seconds: a PATCH waits for a running save_run instead of failing
    eng = create_engine(f"sqlite:///{p}" if p != ":memory:" else "sqlite://", connect_args={"timeout": 30})
    SQLModel.metadata.create_all(eng)
    _add_missing_columns(eng)
    return eng


def _add_missing_columns(eng) -> None:
    """create_all never alters existing tables: add columns that newer models have (additive only)."""
    from sqlalchemy import inspect, text
    insp = inspect(eng)
    with eng.begin() as cx:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(dialect=eng.dialect)
                    dflt = ""
                    if col.default is not None and getattr(col.default, "is_scalar", False):
                        v = col.default.arg
                        dflt = f" DEFAULT {int(v) if isinstance(v, bool) else repr(v)}"
                    cx.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{dflt}'))


SIZE_SOFT, SIZE_HARD = 32_000, 128_000


def size_warning(tokens: int) -> Optional[str]:
    """Warning text for a complete MD of `tokens` o200k tokens, or None."""
    if tokens > SIZE_HARD:
        return f"about {tokens:,} tokens — larger than many LLM context windows (128k–200k)"
    if tokens > SIZE_SOFT:
        return f"about {tokens:,} tokens — fits large context windows but is heavy for smaller models (32k)"
    return None


def match_topics(old: list[Topic], new_embs: np.ndarray, min_sim: float = MATCH_SIM) -> dict[int, int]:
    """Hungarian match of new topic index -> old topic id by embedding cosine (>= min_sim)."""
    old = [t for t in old if t.embedding]
    if not old or len(new_embs) == 0:
        return {}
    O = np.stack([bytes_to_vec(t.embedding) for t in old])
    O = O / np.maximum(np.linalg.norm(O, axis=1, keepdims=True), 1e-9)
    N = new_embs / np.maximum(np.linalg.norm(new_embs, axis=1, keepdims=True), 1e-9)
    S = N @ O.T
    r, c = linear_sum_assignment(-S)
    return {int(i): old[j].id for i, j in zip(r, c) if S[i, j] >= min_sim}


def save_run(eng, *, preset: str, params: dict, timings: dict, docs: list[dict], chunks: list[dict],
             topics: list[dict], links: list[dict]) -> dict:
    """Persist a pipeline run in ONE transaction (all or nothing).

    docs:   {id, format, status, tokens, note, content_hash?}
    chunks: {doc_id, idx, heading_path, text, tokens}
    topics: {name, description, synonyms, embedding(np), centroid(np)}
    links:  {doc_id, topic(index into topics), score, confidence, evidence(list)}
    Scope: only documents in `docs` lose their old AI links/chunks; other documents keep everything.
    Human links are re-read INSIDE the transaction (SQLite holds the write lock from the first flush),
    so a link that became human while the run was computing is never overwritten.
    A human link on a document whose content_hash changed is kept but flagged content_changed.
    Returns {"run_id", "topic_ids", "kept_human", "new_links", "human_on_retired_topics", "content_changed_links"}.
    """
    run_doc_ids = {d["id"] for d in docs}
    with Session(eng) as s:
        run = Run(preset=preset, params=json.dumps(params), timings=json.dumps(timings),
                  n_docs=len(docs), n_topics=len(topics))
        s.add(run)
        s.flush()   # takes the write lock; everything below is read under it

        changed_docs: set[str] = set()
        for d in docs:
            row = s.get(Document, d["id"]) or Document(id=d["id"])
            new_hash = d.get("content_hash", "")
            if row.content_hash and new_hash and row.content_hash != new_hash:
                changed_docs.add(d["id"])
            row.format, row.status, row.tokens, row.note = d["format"], d["status"], d["tokens"], d.get("note", "")
            row.token_count = d.get("token_count", d["tokens"])
            row.size_warning = d.get("size_warning", size_warning(row.token_count))
            if new_hash:
                row.content_hash = new_hash
            row.updated_at = _now()
            s.add(row)
        for old in s.exec(select(Chunk).where(Chunk.doc_id.in_(run_doc_ids))).all() if run_doc_ids else []:
            s.delete(old)
        s.flush()
        for c in chunks:
            s.add(Chunk(id=f"{c['doc_id']}#{c['idx']}", doc_id=c["doc_id"], idx=c["idx"],
                        heading_path=c["heading_path"], text=c["text"], tokens=c["tokens"]))

        # --- topics: keep ids stable by matching to previous active topics
        old = list(s.exec(select(Topic).where(Topic.active == True)).all())  # noqa: E712
        new_embs = np.stack([t["embedding"] for t in topics]) if topics else np.zeros((0, 1))
        match = match_topics(old, new_embs)
        old_by_id = {t.id: t for t in old}
        topic_ids: list[int] = []
        for i, t in enumerate(topics):
            if i in match:
                row = old_by_id[match[i]]
                if not row.name_locked:
                    row.name, row.description = t["name"], t["description"]
                row.synonyms = json.dumps(t["synonyms"])
            else:
                row = Topic(name=t["name"], description=t["description"], synonyms=json.dumps(t["synonyms"]))
            row.embedding = vec_to_bytes(t["embedding"])
            row.centroid = vec_to_bytes(t["centroid"])
            row.active, row.run_id = True, run.id
            s.add(row)
            s.flush()
            topic_ids.append(row.id)
        retired = [t for t in old if t.id not in topic_ids]
        for t in retired:
            t.active = False
            s.add(t)

        # --- links: replace AI links of the docs in this run only; keep every human link
        if run_doc_ids:
            for l in s.exec(select(Link).where(Link.source == "ai", Link.doc_id.in_(run_doc_ids))).all():
                s.delete(l)
        s.flush()
        human_links = list(s.exec(select(Link).where(Link.source == "human")).all())
        human = {(l.doc_id, l.topic_id) for l in human_links}
        n_flag = 0
        for l in human_links:
            if l.doc_id in changed_docs and not l.content_changed:
                l.content_changed = True
                s.add(l)
                n_flag += 1
        retired_ids = {t.id for t in retired}
        human_on_retired = sum(1 for l in human_links if l.topic_id in retired_ids)
        n_new = 0
        for l in links:
            tid = topic_ids[l["topic"]]
            if (l["doc_id"], tid) in human:
                continue
            ev = [{**e, "chunk": f"{l['doc_id']}#{chunks_idx(chunks, e['chunk'], l['doc_id'])}"}
                  if isinstance(e.get("chunk"), int) else e for e in l.get("evidence", [])]
            s.add(Link(doc_id=l["doc_id"], topic_id=tid, score=l["score"], confidence=l["confidence"],
                       status="proposed", source="ai", evidence=json.dumps(ev),
                       role=l.get("role", "primary"), disagreement=bool(l.get("disagreement", False))))
            n_new += 1
        s.commit()
        return {"run_id": run.id, "topic_ids": topic_ids, "kept_human": len(human), "new_links": n_new,
                "human_on_retired_topics": human_on_retired, "content_changed_links": n_flag}


def chunks_idx(chunks: list[dict], global_idx: int, doc_id: str) -> int:
    """Evidence refers to the global chunk list position; map it to the chunk's per-doc idx."""
    try:
        return chunks[global_idx]["idx"]
    except (IndexError, KeyError):
        return 0


def human_set_link(eng, doc_id: str, topic_id: int, status: str, moved_to: int | None = None) -> None:
    """Record a human decision. Moving also creates an accepted human link at the target topic."""
    assert status in ("accepted", "rejected", "moved")
    with Session(eng) as s:
        def upsert(tid: int, st: str, mv: int | None):
            l = s.exec(select(Link).where(Link.doc_id == doc_id, Link.topic_id == tid)).first()
            if l is None:
                l = Link(doc_id=doc_id, topic_id=tid)
            l.status, l.moved_to, l.source, l.reviewed_at = st, mv, "human", _now()
            l.content_changed = False   # a fresh human decision is on the current content
            s.add(l)
        upsert(topic_id, status, moved_to if status == "moved" else None)
        if status == "moved" and moved_to is not None:
            upsert(moved_to, "accepted", None)
        s.commit()
