"""CLI: uv run python -m docmap.pipeline ..\\corpus\\raw --preset nim
convert (if needed) -> chunk -> embed -> topics -> link -> store; prints a summary."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

from . import paths, store
from .chunk import chunk_markdown, clean_title
from .link import BLEND, PROFILE_TAU, TAU, THRESHOLD, link_docs, link_docs_profile
from .llm import get_models
from .induce import induce_and_link
from .topics import discover, discover_profiles
from .profile import build_profiles, profile_text, profile_texts

from .convert import ALLOWED_EXTS as EXTS   # single source of truth for supported types


def candidate_files(raw_dir: Path) -> list[Path]:
    """Every regular, non-hidden file. Unsupported types are NOT dropped: convert() reports them as
    status "unsupported" with a message, and they are stored as Document rows so the UI shows them."""
    return [p for p in sorted(raw_dir.iterdir()) if p.is_file() and not p.name.startswith((".", "~$"))]
MD_DIR = paths.md_dir()   # env DOCMAP_MD_DIR or data\md; the CLI flags call configure()
META = MD_DIR / "_meta.json"   # {doc: conversion mode that wrote its .md}
TOK_CACHE = paths.cache_dir() / "md_tokens.json"
MAX_MD_CHARS = 150_000      # LINKING ONLY: very large docs are cut here before chunking. Stored MD is never cut.
MAX_CHUNKS_PER_DOC = 24     # evenly sampled, so one big file cannot dominate the clusters


def configure(md_dir=None, cache_dir=None, scratch_dir=None) -> None:
    """Point this module at other folders (CLI flags --md-dir / --cache-dir). Also sets the DOCMAP_* env vars
    so llm.py's embedding and answer caches follow."""
    global MD_DIR, META, TOK_CACHE
    paths.set_env(md_dir=md_dir, cache_dir=cache_dir, scratch_dir=scratch_dir)
    MD_DIR = paths.md_dir()
    META = MD_DIR / "_meta.json"
    TOK_CACHE = paths.cache_dir() / "md_tokens.json"


CONVERTER_VERSION = "conv-1"   # bump when convert.py/slim.py output changes: forces a re-convert of every doc


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def load_docs(raw_dir: Path, digest: bool = False, md_dir: Path | None = None, on_progress=None) -> list[dict]:
    """Return doc dicts {id, format, status, note, md, content_hash}.

    The cached data/md/<name>.md is reused ONLY when _meta.json holds the same sha256 of the raw file,
    the same mode and the same converter version for that name. A changed file with the same name is
    therefore converted again (and profiled/linked again, because the profile cache is keyed by text).
    Default mode is 'full' (every row); digest=True is the opt-in lossy digest."""
    md_dir = md_dir or MD_DIR
    meta_path = md_dir / "_meta.json"
    md_dir.mkdir(parents=True, exist_ok=True)
    want = "digest" if digest else "full"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    files = candidate_files(raw_dir)
    docs = []
    for n, p in enumerate(files, 1):
        if on_progress:
            on_progress("convert", n - 1, len(files))
        md_path = md_dir / f"{p.name}.md"
        sha = file_sha256(p)
        d = {"id": p.name, "format": p.suffix.lower().lstrip("."), "status": "ok", "note": "", "md": "",
             "content_hash": sha}
        m = meta.get(p.name)
        fresh = (isinstance(m, dict) and m.get("sha256") == sha and m.get("mode") == want
                 and m.get("converter") == CONVERTER_VERSION)   # legacy string entries count as stale
        if fresh and md_path.exists() and md_path.stat().st_size > 0:
            d["md"] = md_path.read_text(encoding="utf-8")
        else:
            from .convert import convert
            from .slim import slim
            res = convert(p, mode="auto" if digest else "full")
            d["status"] = res.status
            d["note"] = "; ".join(res.warnings)   # stored in full; the UI truncates visually
            if res.markdown:
                d["md"] = slim(res.markdown)
                md_path.write_text(d["md"], encoding="utf-8")
                meta[p.name] = {"sha256": sha, "mode": want, "converter": CONVERTER_VERSION}
            else:
                meta.pop(p.name, None)   # no usable MD now: never leave an old one marked fresh
                md_path.unlink(missing_ok=True)
            meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        docs.append(d)
    if on_progress:
        on_progress("convert", len(files), len(files))
    return docs


def make_blind_dir(raw_dir: Path, out_dir: Path, map_csv: Path | None = None) -> dict[str, str]:
    """Copy supported files to out_dir as doc-01.<ext>, doc-02.<ext>... (sorted by original name).
    Returns {neutral name: original name}; optionally saves the mapping as CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.iterdir():
        if old.is_file():
            old.unlink()
    mapping: dict[str, str] = {}
    for i, p in enumerate((q for q in candidate_files(raw_dir)), 1):
        neutral = f"doc-{i:02d}{p.suffix.lower()}"
        shutil.copy2(p, out_dir / neutral)
        mapping[neutral] = p.name
    if map_csv:
        map_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(map_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["blind_name", "original_name"])
            w.writerows(mapping.items())
    return mapping


def md_tokens(name: str, md: str, md_dir: Path | None = None) -> int:
    """o200k tokens of the COMPLETE slim MD (cached by file mtime/size: an 8 M-token sheet is slow to count)."""
    from .tokens import count
    p = (md_dir or MD_DIR) / f"{name}.md"
    key = f"{name}|{p.stat().st_mtime_ns}|{p.stat().st_size}" if p.exists() else ""
    try:
        cache = json.loads(TOK_CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    if key and key in cache:
        return cache[key]
    n = count(md)
    if key:
        cache[key] = n
        TOK_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return n


def sample_chunks(doc_id: str, md: str):
    md = md[:MAX_MD_CHARS]
    ch = chunk_markdown(doc_id, md)
    if len(ch) > MAX_CHUNKS_PER_DOC:
        pick = np.linspace(0, len(ch) - 1, MAX_CHUNKS_PER_DOC).round().astype(int)
        ch = [ch[i] for i in sorted(set(pick.tolist()))]
    return ch


def run_pipeline(raw_dir: Path, preset: str | None = None, db: Path | str = store.DB_PATH,
                 rerank: bool | None = None, k_range=(3, 10), blend: float = BLEND, tau: float = TAU,
                 threshold: float = THRESHOLD, verbose: bool = True, mode: str = "profile",
                 title_prefix: bool = True, center: bool = True, method: str = "induce", cold: bool = False,
                 digest: bool = False, on_progress=None, blind: bool = False,
                 blind_map_csv: Path | None = None, _blind_map: dict | None = None,
                 _md_dir: Path | None = None) -> dict:
    """on_progress(stage: str, done: int, total: int) is called as the run advances. Stages, in order:
    convert (per doc), chunk, embed, profile (per doc), induce, save. Exceptions in the callback are ignored.

    blind=True: copy the files to a temp dir under neutral names (doc-01.pdf ...), run there, and map every
    id back to the original name before saving. No original file name reaches any LLM or embedding prompt."""
    cb = on_progress

    def prog(stage, done, total):
        if cb:
            try:
                cb(stage, int(done), int(total))
            except Exception:
                pass

    if blind:
        tmp = Path(tempfile.mkdtemp(prefix="docmap_blind_"))
        try:
            bmap = make_blind_dir(raw_dir, tmp / "raw", blind_map_csv)
            return run_pipeline(tmp / "raw", preset, db, rerank, k_range, blend, tau, threshold, verbose, mode,
                                title_prefix, center, method, cold, digest, on_progress, False, None,
                                _blind_map=bmap, _md_dir=MD_DIR / "_blind")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    T: dict[str, float] = {}
    t0 = time.perf_counter()

    def lap(name, since):
        T[name] = round(time.perf_counter() - since, 2)
        return time.perf_counter()

    models = get_models(preset)
    models.cold = cold
    t = time.perf_counter()
    docs = load_docs(raw_dir, digest, _md_dir, prog)
    t = lap("convert", t)
    prog("chunk", 0, len(docs))
    chunks = []
    for d in docs:
        if d["md"].strip():
            chunks.extend(sample_chunks(d["id"], d["md"]))
    t = lap("chunk", t)
    prog("chunk", len(docs), len(docs))
    prog("embed", 0, 1)
    texts = [(clean_title(c.doc_id) + "\n" if title_prefix else "") + (c.heading_path + "\n" if c.heading_path else "")
             + c.text for c in chunks]
    X = models.embed(texts, "passage")
    mu = None
    if mode == "profile" or method == "induce":
        t = lap("embed", t)
        prog("embed", 1, 1)
        profs = build_profiles(models, chunks, on_progress=prog)
        t = lap("profile", t)
        doc_ids = sorted(profs)
        ptexts = {d: profile_text(d, profs[d]) for d in doc_ids}
        flat = [(d, x) for d in doc_ids for x in profile_texts(d, profs[d])]
        E = models.embed([x for _, x in flat], "passage")
        P = np.stack([E[[i for i, (dd, _) in enumerate(flat) if dd == d]].mean(axis=0) for d in doc_ids])
        P = P / np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-9)
        mu_p = P.mean(axis=0)
        P = P - mu_p
        P = P / np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-9)
        if method == "induce":
            n = len(doc_ids)
            hi = min(7, max(2, n // 2))
            prog("induce", 0, 1)
            topics, links, info = induce_and_link(models, chunks, X, doc_ids, P, ptexts, mu_p,
                                                  [c.doc_id for c in chunks], min(4, hi), hi)
            t = lap("induce", t)
            prog("induce", 1, 1)
            return _finish(models, docs, chunks, topics, links, info, T, t0, db, rerank, k_range, blend, tau,
                           threshold, "induce", title_prefix, center, verbose, profs, prog, _blind_map, _md_dir)
        topics, info = discover_profiles(models, doc_ids, ptexts, P, [c.doc_id for c in chunks], (k_range[0], max(k_range[0], min(k_range[1], math.ceil(math.sqrt(len(doc_ids)))))), mu_p=mu_p)  # sqrt(n) rule of thumb caps k
        t = lap("topics", t)
        links = link_docs_profile(chunks, X, doc_ids, P, topics, tau=PROFILE_TAU if tau == TAU else tau,
                                  threshold=threshold, summaries=ptexts)
        t = lap("link", t)
        return _finish(models, docs, chunks, topics, links, info, T, t0, db, rerank, k_range, blend, tau, threshold,
                       mode, title_prefix, center, verbose, profs, prog, _blind_map, _md_dir)
    if center:  # remove the component shared by every chunk (the corpus-wide "Environment Agency" signal)
        mu = X.mean(axis=0)
        X = X - mu
        X = X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
    t = lap("embed", t)
    topics, info = discover(models, chunks, X, k_range, mode=mode, mu=mu)
    t = lap("topics", t)
    links = link_docs(models, chunks, X, topics, rerank=rerank, blend=blend, tau=tau, threshold=threshold)
    t = lap("link", t)
    return _finish(models, docs, chunks, topics, links, info, T, t0, db, rerank, k_range, blend, tau, threshold,
                   mode, title_prefix, center, verbose, None, prog, _blind_map, _md_dir)


def _finish(models, docs, chunks, topics, links, info, T, t0, db, rerank, k_range, blend, tau, threshold,
            mode, title_prefix, center, verbose, profs, prog=None, blind_map=None, md_dir=None) -> dict:
    eng = store.get_engine(db)
    from .tokens import count
    doc_rows = [{"id": d["id"], "format": d["format"], "status": d["status"] if not d["md"].strip() else "ok",
                 "tokens": md_tokens(d["id"], d["md"], md_dir) if d["md"] else 0, "note": d["note"],
                 "content_hash": d.get("content_hash", "")} for d in docs]
    for r in doc_rows:
        r["token_count"] = r["tokens"]
        r["size_warning"] = store.size_warning(r["tokens"])
    chunk_rows = [{"doc_id": c.doc_id, "idx": c.idx, "heading_path": c.heading_path, "text": c.text,
                   "tokens": c.tokens} for c in chunks]
    topic_rows = [{"name": x.name, "description": x.description, "synonyms": x.synonyms,
                   "embedding": x.emb, "centroid": x.centroid} for x in topics]
    link_rows = [{"doc_id": l.doc_id, "topic": l.topic, "score": l.score, "confidence": l.confidence,
                  "evidence": l.evidence, "role": getattr(l, "role", "primary"),
                  "disagreement": getattr(l, "disagreement", False)} for l in links]
    if blind_map:   # blind run: restore the real names before saving, so results score against gold.csv
        for r in doc_rows:
            r["id"] = blind_map.get(r["id"], r["id"])
        for r in chunk_rows:
            r["doc_id"] = blind_map.get(r["doc_id"], r["doc_id"])
        for r in link_rows:
            r["doc_id"] = blind_map.get(r["doc_id"], r["doc_id"])
        for d in docs:
            d["id"] = blind_map.get(d["id"], d["id"])
    if prog:
        prog("save", 0, 1)
    T["total"] = round(time.perf_counter() - t0, 2)
    res = store.save_run(eng, preset=models.cfg["PRESET"], params={"k": info, "blend": blend, "tau": tau,
                         "threshold": threshold, "rerank": rerank, "mode": mode, "method": info.get("method", "cluster"), "title_prefix": title_prefix, "center": center, "models": [models.cfg["EMBED_MODEL"],
                         models.cfg["LLM_MODEL"]]}, timings=T, docs=doc_rows, chunks=chunk_rows,
                         topics=topic_rows, links=link_rows)
    if prog:
        prog("save", 1, 1)
    out = {"timings": T, "cluster_info": info, "stats": models.stats, "store": res, "n_chunks": len(chunks),
           "topics": [(x.name, len(x.members)) for x in topics]}
    if verbose:
        print_summary(out, topics, links, docs)
    return out


def print_summary(out, topics, links, docs):
    ci = out["cluster_info"]
    print(f"\nmethod: {ci['algo']} k={ci['k']} silhouette={ci['silhouette']} "
          f"(before merge/drop {ci['clusters_before_merge']}, after {ci['topics_after_merge']})")
    top: dict[int, list[str]] = {}
    best: dict[str, tuple] = {}
    for l in links:
        if l.doc_id not in best or l.confidence > best[l.doc_id][1]:
            best[l.doc_id] = (l.topic, l.confidence)
    for d, (k, _) in best.items():
        top.setdefault(k, []).append(d)
    nlinks: dict[int, int] = {}
    for l in links:
        nlinks[l.topic] = nlinks.get(l.topic, 0) + 1
    print(f"{'#':<3}{'topic':<42}{'chunks':>7}{'top-docs':>9}{'links':>7}")
    for i, t in enumerate(topics):
        print(f"{i:<3}{t.name[:40]:<42}{len(t.members):>7}{len(top.get(i, [])):>9}{nlinks.get(i, 0):>7}")
    nolinks = [d["id"] for d in docs if d["id"] not in best]
    if nolinks:
        print("no links (no text):", ", ".join(nolinks))
    T = out["timings"]
    print("timings (s):", ", ".join(f"{k}={v}" for k, v in T.items()))
    print("calls:", out["stats"], "chunks:", out["n_chunks"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_dir")
    ap.add_argument("--preset", default=None, choices=["nim", "local"])
    ap.add_argument("--db", default=str(store.DB_PATH))
    ap.add_argument("--rerank", choices=["on", "off", "auto"], default="auto")
    ap.add_argument("--kmin", type=int, default=3)
    ap.add_argument("--kmax", type=int, default=10)
    ap.add_argument("--blend", type=float, default=BLEND)
    ap.add_argument("--tau", type=float, default=TAU)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--no-center", action="store_true", help="skip subtracting the corpus-mean embedding")
    ap.add_argument("--method", choices=["induce", "cluster"], default="induce",
                    help="induce = LLM theme induction (default); cluster = the older profile clustering")
    ap.add_argument("--cold", action="store_true", help="bypass LLM profile/theme caches (embeddings cache stays)")
    ap.add_argument("--digest", action="store_true", help="opt-in lossy spreadsheet digest instead of full conversion")
    ap.add_argument("--blind", action="store_true",
                    help="eval mode: run on neutral file names (doc-01.pdf ...), map back before saving")
    ap.add_argument("--md-dir", default=None, help="converted Markdown folder (env DOCMAP_MD_DIR; default data/md)")
    ap.add_argument("--cache-dir", default=None, help="embedding + LLM answer caches (env DOCMAP_CACHE_DIR; default data/cache)")
    ap.add_argument("--notes-dir", default=None, help="where --blind writes blind-map-main.csv (env DOCMAP_NOTES_DIR)")
    ap.add_argument("--mode", choices=["chunk", "doc", "profile"], default="profile")
    ap.add_argument("--no-title", action="store_true", help="do not prefix chunk text with the document title")
    a = ap.parse_args()
    rr = {"on": True, "off": False, "auto": None}[a.rerank]
    configure(a.md_dir, a.cache_dir)
    paths.set_env(notes_dir=a.notes_dir)
    out = run_pipeline(Path(a.raw_dir), a.preset, a.db, rr, (a.kmin, a.kmax), a.blend, a.tau, a.threshold,
                       mode=a.mode, title_prefix=not a.no_title, center=not a.no_center,
                       method=a.method, cold=a.cold, digest=a.digest, blind=a.blind,
                       blind_map_csv=paths.notes_dir() / "blind-map-main.csv" if a.blind else None)
    (paths.cache_dir().parent / "last_run.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
