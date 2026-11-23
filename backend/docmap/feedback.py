"""Human-in-the-loop learning: accepted/moved links become topic examples, rejected links become negatives;
the still-open AI links are re-scored against the updated topic prototypes.

Prototype = normalize((1 - alpha) * topic text embedding + alpha * mean(example doc embeddings)).
Doc embedding = embedding of the doc's LLM profile text when it can be built from cache, else the mean of
its chunk embeddings (same texts the pipeline embeds, so the embedding cache is reused).

Confidence shift: new confidence = old confidence + the change the examples cause in a softmax over topics
(prototype with examples minus text-only prototype). With no reviews nothing changes, and the pipeline's own
confidence scale is kept. Human links are never touched. Moves are only suggested, never applied.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

import numpy as np
from sqlmodel import Session, select

from . import store
from .chunk import Chunk as ChunkT, clean_title
from .llm import get_models
from .profile import build_profiles, profile_text

TAU = 0.10            # softmax temperature (softer than the pipeline's 0.05: few examples, keep shifts modest)
MAX_SHIFT = 0.25      # one rescore moves a confidence by at most this much (before the negative penalty)
NEG_SIM = 0.9         # doc this similar to a human-rejected doc of the topic gets a penalty
NEG_PENALTY = 0.10
SUGGEST_MARGIN = 0.05
EPS = 1e-6


@dataclass
class RescoreResult:
    changed: list = field(default_factory=list)          # (link_id, old_conf, new_conf, old_topic, new_top_topic)
    examples_per_topic: dict = field(default_factory=dict)   # topic_id -> n accepted examples
    negatives_per_topic: dict = field(default_factory=dict)
    suggested_topic_id: dict = field(default_factory=dict)   # link_id -> topic that clearly beats the current one
    n_open: int = 0                                      # unreviewed AI links looked at
    n_reviews: int = 0                                   # human links used (accepted + rejected + moved)
    dry_run: bool = False


def _norm(a: np.ndarray) -> np.ndarray:
    return a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-9)


def _softmax(S: np.ndarray, tau: float = TAU) -> np.ndarray:
    z = S / tau
    z = z - z.max(axis=-1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=-1, keepdims=True)


def _topic_text(t) -> str:
    try:
        syn = ", ".join(json.loads(t.synonyms or "[]"))
    except Exception:
        syn = ""
    return f"{t.name}: {t.description} Synonyms: {syn}"


def _doc_embeddings(models, s: Session, doc_ids: list[str]) -> dict[str, np.ndarray]:
    rows = s.exec(select(store.Chunk)).all()
    by_doc: dict[str, list] = {}
    for c in rows:
        if c.doc_id in doc_ids:
            by_doc.setdefault(c.doc_id, []).append(c)
    for v in by_doc.values():
        v.sort(key=lambda c: c.idx)
    chunks = [ChunkT(c.doc_id, c.idx, c.heading_path, c.text, c.tokens) for v in by_doc.values() for c in v]
    # profiles: cache only (never call the LLM here); use them only if EVERY doc has one, so all docs share one space
    class _CacheOnly:
        def __init__(self, m):
            self._m = m

        def __getattr__(self, name):
            return getattr(self._m, name)

        def cached_json(self, version, system, user, max_tokens=700):
            hit = None if getattr(self._m, "cold", False) else self._m.jcache.get(
                self._m.jcache.key(self._m.cfg["LLM_MODEL"], version, system, user))
            if hit is None:
                raise LookupError("profile not cached")
            return hit

    try:
        profs = build_profiles(_CacheOnly(models), chunks)
    except Exception:
        profs = {}
    out: dict[str, np.ndarray] = {}
    ptexts = {d: profile_text(d, p) for d, p in profs.items() if p.get("summary")}
    if ptexts and all(d in ptexts for d in doc_ids):
        E = models.embed([ptexts[d] for d in doc_ids], "passage")
        out.update({d: E[i] for i, d in enumerate(doc_ids)})
    for d in doc_ids:
        if d in out or d not in by_doc:
            continue
        texts = [clean_title(d) + chr(10) + (c.heading_path + chr(10) if c.heading_path else "") + c.text
                 for c in by_doc[d]]
        out[d] = _norm(models.embed(texts, "passage").mean(axis=0))
    return {d: _norm(v) for d, v in out.items()}


def rescore(db_path, *, preset: str | None = None, alpha: float = 0.5, dry_run: bool = False,
            models=None) -> RescoreResult:
    eng = store.get_engine(db_path)
    res = RescoreResult(dry_run=dry_run)
    with Session(eng) as s:
        topics = list(s.exec(select(store.Topic).where(store.Topic.active == True)).all())  # noqa: E712
        links = list(s.exec(select(store.Link)).all())
        if not topics:
            return res
        tids = [t.id for t in topics]
        human = [l for l in links if l.source == "human"]
        res.n_reviews = len(human)
        pos: dict[int, set] = {t: set() for t in tids}
        neg: dict[int, set] = {t: set() for t in tids}
        for l in human:
            if l.status == "accepted" and l.topic_id in pos:
                pos[l.topic_id].add(l.doc_id)
            elif l.status == "moved" and l.moved_to in pos:
                pos[l.moved_to].add(l.doc_id)       # the moved-to link is also stored as accepted
            if l.status in ("rejected", "moved") and l.topic_id in neg:
                neg[l.topic_id].add(l.doc_id)       # a moved-from topic was judged wrong for this doc
        for t in tids:   # a doc a human accepted for a topic is never a negative for it
            neg[t] -= pos[t]
        res.examples_per_topic = {t: len(pos[t]) for t in tids}
        res.negatives_per_topic = {t: len(neg[t]) for t in tids}
        open_links = [l for l in links if l.source != "human" and l.topic_id in tids]
        res.n_open = len(open_links)
        if not open_links or not human:
            return res

        models = models or get_models(preset)
        need = sorted({l.doc_id for l in open_links} | {d for t in tids for d in pos[t] | neg[t]})
        D = _doc_embeddings(models, s, need)
        if not D:
            return res
        T = _norm(models.embed([_topic_text(t) for t in topics], "passage"))
        mu = np.mean(list(D.values()), axis=0)
        Tc = _norm(T - mu)                                    # centred space (as the pipeline does)
        Pr = Tc.copy()
        for i, t in enumerate(tids):
            ex = [_norm(D[d] - mu) for d in pos[t] if d in D]
            if ex:
                Pr[i] = _norm((1 - alpha) * Tc[i] + alpha * _norm(np.mean(ex, axis=0)))
        pi = {t: i for i, t in enumerate(tids)}
        by_doc: dict[str, list] = {}
        for l in open_links:
            by_doc.setdefault(l.doc_id, []).append(l)
        for d, ls in by_doc.items():
            if d not in D:
                continue
            x = _norm(D[d] - mu)
            p_new = _softmax(Pr @ x)
            p_old = _softmax(Tc @ x)
            best = int(np.argmax(p_new))
            for l in ls:
                i = pi[l.topic_id]
                new = l.confidence + float(np.clip(p_new[i] - p_old[i], -MAX_SHIFT, MAX_SHIFT))
                negs = [n for n in neg[l.topic_id] if n in D and n != d]
                if negs and max(float(D[d] @ D[n]) for n in negs) > NEG_SIM:
                    new -= NEG_PENALTY
                new = round(min(1.0, max(0.0, new)), 4)
                sug = None
                if tids[best] != l.topic_id and p_new[best] - p_new[i] > SUGGEST_MARGIN:
                    sug = tids[best]
                    res.suggested_topic_id[l.id] = sug
                if abs(new - l.confidence) > EPS or sug is not None:
                    res.changed.append((l.id, l.confidence, new, l.topic_id, tids[best]))
                    if not dry_run and abs(new - l.confidence) > EPS:
                        l.confidence = new
                        s.add(l)
        if not dry_run:
            s.commit()
    return res


def format_table(res: RescoreResult, names: dict[int, str] | None = None) -> str:
    names = names or {}
    lines = [f"{'link':>5}  {'old':>6} -> {'new':>6}  {'topic':<28} suggested"]
    for lid, o, n, ot, nt in res.changed:
        sug = names.get(nt, nt) if lid in res.suggested_topic_id else ""
        lines.append(f"{lid:>5}  {o:>6.3f} -> {n:>6.3f}  {str(names.get(ot, ot))[:28]:<28} {sug}")
    lines.append(f"Re-scored {len(res.changed)} of {res.n_open} open links using your {res.n_reviews} reviews"
                 + (" (dry run, nothing written)" if res.dry_run else ""))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-score open AI links from human reviews")
    ap.add_argument("--db", default=str(store.DB_PATH))
    ap.add_argument("--preset", default=None)
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    res = rescore(a.db, preset=a.preset, alpha=a.alpha, dry_run=a.dry_run)
    eng = store.get_engine(a.db)
    with Session(eng) as s:
        names = {t.id: t.name for t in s.exec(select(store.Topic)).all()}
    print(format_table(res, names))
    print("examples per topic:", {names.get(k, k): v for k, v in res.examples_per_topic.items()})


if __name__ == "__main__":
    main()
