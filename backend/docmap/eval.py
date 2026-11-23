"""Eval: uv run python -m docmap.eval --gold ..\\corpus\\gold.csv [--db ...] [--label text]

Maps AI topics to gold themes with the Hungarian algorithm on the doc-overlap matrix, scores each
doc's top predicted topic against the gold primary (strict) or primary/secondary (lenient), and
computes the per-topic context-pack token metric. Writes notes/metrics.json, appends to eval-report.md.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from sqlmodel import Session, select

from . import paths, store
from .tokens import count, naive_dump
from .paths import ROOT

NOTES = paths.notes_dir()
RAW = paths.corpus_dir()          # the folder the gold file names refer to (CLI --corpus, env DOCMAP_CORPUS_DIR)
MD_DIR = paths.md_dir()
TOK_CACHE = paths.cache_dir() / "doc_tokens.json"
SCRATCH = paths.scratch_dir()


def configure(corpus=None, md_dir=None, cache_dir=None, scratch_dir=None, notes_dir=None) -> None:
    """Apply CLI flags: sets the DOCMAP_* env vars (llm caches follow) and this module's and pipeline's globals."""
    global NOTES, RAW, MD_DIR, TOK_CACHE, SCRATCH
    from . import pipeline
    paths.set_env(corpus_dir=corpus, md_dir=md_dir, cache_dir=cache_dir, scratch_dir=scratch_dir, notes_dir=notes_dir)
    pipeline.configure(md_dir, cache_dir, scratch_dir)
    NOTES, RAW, MD_DIR, SCRATCH = paths.notes_dir(), paths.corpus_dir(), paths.md_dir(), paths.scratch_dir()
    TOK_CACHE = paths.cache_dir() / "doc_tokens.json"


# ---------- pure helpers (unit-tested)
def hungarian_map(overlap: np.ndarray) -> dict[int, int]:
    """overlap[t, g] = number of docs with predicted topic t and gold primary g. Returns {topic: gold}."""
    if overlap.size == 0:
        return {}
    r, c = linear_sum_assignment(-overlap)
    return {int(i): int(j) for i, j in zip(r, c) if overlap[i, j] > 0}


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score(pred: dict[str, str | None], gold: dict[str, tuple[str, str]], themes: list[str]) -> dict:
    """pred: doc -> predicted gold-theme name (or None). gold: doc -> (primary, secondary)."""
    out = {}
    for mode in ("strict", "lenient"):
        per = {}
        for t in themes:
            tp = fp = fn = 0
            for d, (prim, sec) in gold.items():
                p = pred.get(d)
                ok_set = {prim} if mode == "strict" else {prim, sec} - {""}
                if p == t:
                    if t in ok_set:
                        tp += 1
                    else:
                        fp += 1
                elif prim == t and (p is None or p not in ok_set):
                    fn += 1
            pr, rc, f1 = prf(tp, fp, fn)
            per[t] = {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}
        n_ok = sum(1 for d, (prim, sec) in gold.items()
                   if pred.get(d) in ({prim} if mode == "strict" else ({prim, sec} - {""})))
        out[mode] = {"per_theme": per, "macro_f1": round(float(np.mean([v["f1"] for v in per.values()])), 3),
                     "macro_precision": round(float(np.mean([v["precision"] for v in per.values()])), 3),
                     "macro_recall": round(float(np.mean([v["recall"] for v in per.values()])), 3),
                     "accuracy": round(n_ok / max(len(gold), 1), 3)}
    return out


# ---------- token helpers (cached)
def _tok_cache() -> dict:
    try:
        return json.loads(TOK_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def doc_tokens(name: str) -> dict:
    """{'naive': tokens of naive dump of raw file, 'slim': tokens of slim MD} (cached by mtime)."""
    cache = _tok_cache()
    raw, md = RAW / name, MD_DIR / f"{name}.md"
    key = f"{name}|{raw.stat().st_mtime_ns if raw.exists() else 0}|{md.stat().st_mtime_ns if md.exists() else 0}"
    if key in cache:
        return cache[key]
    res = {"naive": 0, "slim": 0}
    try:
        res["naive"] = count(naive_dump(raw))
    except Exception:
        pass
    if md.exists():
        res["slim"] = count(md.read_text(encoding="utf-8"))
    cache[key] = res
    TOK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOK_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return res


def read_gold(path: Path):
    gold = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            gold[r["file"]] = (r["theme"].strip(), (r.get("secondary_theme") or "").strip())
    return gold


def evaluate(gold_path: Path, db: Path | str = store.DB_PATH) -> dict:
    gold = read_gold(gold_path)
    themes = sorted({p for p, _ in gold.values()})
    eng = store.get_engine(db)
    with Session(eng) as s:
        topics = {t.id: t for t in s.exec(select(store.Topic).where(store.Topic.active == True)).all()}  # noqa: E712
        links = [l for l in s.exec(select(store.Link)).all() if l.status not in ("rejected", "moved")]
        runs = s.exec(select(store.Run)).all()
        doc_status = {d.id: d.status for d in s.exec(select(store.Document)).all()}
    run = runs[-1] if runs else None
    tids = sorted(topics)
    best: dict[str, int] = {}
    conf: dict[str, float] = {}
    for l in links:
        if l.topic_id in topics and l.doc_id in gold and l.confidence >= conf.get(l.doc_id, -1):
            best[l.doc_id], conf[l.doc_id] = l.topic_id, l.confidence
    gi = {g: i for i, g in enumerate(themes)}
    ov = np.zeros((len(tids), len(themes)), dtype=int)
    for d, t in best.items():
        ov[tids.index(t), gi[gold[d][0]]] += 1
    mapping = hungarian_map(ov)
    t2g = {tids[i]: themes[j] for i, j in mapping.items()}
    pred = {d: t2g.get(t) for d, t in best.items()}
    sc = score(pred, gold, themes)
    unlinked = [d for d in gold if d not in best]

    # confusion: rows gold primary, cols predicted theme/topic name
    confusion = {g: {} for g in themes}
    for d, (prim, _) in gold.items():
        key = pred.get(d) or ("(unmatched topic: " + topics[best[d]].name + ")" if d in best else "(no link)")
        confusion[prim][key] = confusion[prim].get(key, 0) + 1

    # context pack: docs linked (non-rejected) to the topic matched to each gold theme
    dt = {d: doc_tokens(d) for d in gold}
    corpus_naive = sum(v["naive"] for v in dt.values())
    corpus_slim = sum(v["slim"] for v in dt.values())
    packs = {}
    g2t = {themes[j]: tids[i] for i, j in mapping.items()}
    for g in themes:
        t = g2t.get(g)
        docs = sorted({l.doc_id for l in links if l.topic_id == t and l.doc_id in gold}) if t else []
        pack = sum(dt[d]["slim"] for d in docs)
        packs[g] = {"topic": topics[t].name if t else None, "docs": len(docs), "pack_tokens": pack,
                    "vs_naive_corpus": corpus_naive, "reduction_pct": round(100 * (1 - pack / corpus_naive), 2) if corpus_naive else None,
                    "gold_docs_naive_tokens": sum(dt[d]["naive"] for d, (p, _) in gold.items() if p == g)}
    res = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "db": str(db), "preset": run.preset if run else None,
        "run_params": json.loads(run.params) if run else None,
        "timings_s": json.loads(run.timings) if run else None,
        "n_docs_gold": len(gold), "n_docs_linked": len(best), "unlinked_docs": unlinked,
        "unlinkable": {d: doc_status.get(d, "missing") for d in unlinked},   # e.g. needs_ocr: no text to link
        "topics": [{"id": i, "name": topics[i].name, "gold_theme": t2g.get(i)} for i in tids],
        "mapping": {topics[t].name: g for t, g in t2g.items()},
        "strict": sc["strict"], "lenient": sc["lenient"],
        "confusion": confusion,
        "context_packs": packs,
        "corpus_naive_tokens": corpus_naive, "corpus_slim_tokens": corpus_slim,
    }
    # same scores on the docs that have text only (scanned/errored docs cannot be linked)
    linked_gold = {d: v for d, v in gold.items() if d in best}
    # "without unlinkable": same F1 with the unlinkable docs (needs_ocr/error) removed from the gold set
    res["on_linked_docs"] = {m: v for m, v in score(pred, linked_gold, themes).items()
                             for v in [{"macro_f1": v["macro_f1"], "accuracy": v["accuracy"]}]}
    return res


def report_section(res: dict, label: str) -> str:
    L = [f"\n## Eval {res['when']} - {label}\n",
         f"preset `{res['preset']}`, db `{res['db']}`, docs {res['n_docs_gold']} (linked {res['n_docs_linked']}; "
         f"no link: {', '.join(res['unlinked_docs']) or 'none'})\n",
         f"timings (s): {res['timings_s']}\n", "AI topic to gold theme (Hungarian):\n"]
    for t in res["topics"]:
        L.append(f"- {t['name']} -> {t['gold_theme'] or '(unmatched)'}")
    L.append("\n| mode | macro-P | macro-R | macro-F1 | accuracy | F1 on linked docs only |\n|---|---|---|---|---|---|")
    for m in ("strict", "lenient"):
        v = res[m]
        L.append(f"| {m} | {v['macro_precision']} | {v['macro_recall']} | **{v['macro_f1']}** | {v['accuracy']} | {res['on_linked_docs'][m]['macro_f1']} |")
    L.append("\nPer theme (lenient): " + "; ".join(f"{g}: P{v['precision']} R{v['recall']} F{v['f1']}" for g, v in res["lenient"]["per_theme"].items()))
    L.append("\nConfusion (rows = gold primary, cols = predicted):\n")
    cols = sorted({c for r in res["confusion"].values() for c in r})
    L.append("| gold \\ pred | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols))
    for g, r in res["confusion"].items():
        L.append(f"| {g} | " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    L.append(f"\nContext pack per theme (slim MD of linked docs) vs naive dump of the whole corpus "
             f"({res['corpus_naive_tokens']:,} tokens; whole corpus as slim MD: {res['corpus_slim_tokens']:,}):\n")
    L.append("| gold theme | matched topic | docs | pack tokens | reduction vs naive corpus |\n|---|---|---|---|---|")
    for g, p in res["context_packs"].items():
        L.append(f"| {g} | {p['topic']} | {p['docs']} | {p['pack_tokens']:,} | {p['reduction_pct']}% |")
    return "\n".join(L) + "\n"


def stability(runs: int, preset: str | None, method: str, cold: bool, gold_path: Path, label: str,
              digest: bool = False, blind: bool = False) -> dict:
    """Run the whole pipeline `runs` times into fresh scratch DBs and score each run."""
    import time

    from .pipeline import run_pipeline

    scratch = SCRATCH
    scratch.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(runs):
        db = scratch / f"stab_{label}_{i}.db"
        if db.exists():
            db.unlink()
        t0 = time.perf_counter()
        out = run_pipeline(RAW, preset, db, method=method, cold=cold, digest=digest, verbose=False,
                           blind=blind, blind_map_csv=NOTES / "blind-map-main.csv" if blind else None)
        wall = round(time.perf_counter() - t0, 1)
        r = evaluate(gold_path, db)
        rows.append({"run": i + 1, "wall_s": wall, "strict_f1": r["strict"]["macro_f1"], "lenient_f1": r["lenient"]["macro_f1"],
                     "strict_f1_wo_unlinkable": r["on_linked_docs"]["strict"]["macro_f1"],
                     "lenient_f1_wo_unlinkable": r["on_linked_docs"]["lenient"]["macro_f1"],
                     "lenient_accuracy": r["lenient"]["accuracy"], "n_topics": len(r["topics"]),
                     "topics": [t["name"] for t in r["topics"]], "mapping": r["mapping"],
                     "unlinkable": r["unlinkable"], "timings_s": out["timings"]})
        print(f"run {i + 1}/{runs}: wall {wall}s strict {rows[-1]['strict_f1']} lenient {rows[-1]['lenient_f1']} "
              f"(wo unlinkable {rows[-1]['lenient_f1_wo_unlinkable']}) topics {rows[-1]['topics']}", flush=True)

    def st(key):
        v = np.array([r[key] for r in rows], dtype=float)
        return {"mean": round(float(v.mean()), 3), "min": round(float(v.min()), 3), "max": round(float(v.max()), 3),
                "std": round(float(v.std(ddof=0)), 3)}

    summ = {"label": label, "when": datetime.now().isoformat(timespec="seconds"), "preset": preset or "nim",
            "method": method, "cold": cold, "runs": runs, "per_run": rows,
            "strict": st("strict_f1"), "lenient": st("lenient_f1"),
            "strict_wo_unlinkable": st("strict_f1_wo_unlinkable"), "lenient_wo_unlinkable": st("lenient_f1_wo_unlinkable"),
            "wall_s": st("wall_s")}
    spread = summ["lenient"]["max"] - summ["lenient"]["min"]
    summ["spread_lenient"] = round(spread, 3)
    summ["pass"] = bool(summ["lenient"]["mean"] >= 0.80 and spread <= 0.10 + 1e-9)
    return summ


def stability_section(s: dict) -> str:
    NL = chr(10)
    L = [NL + f"## Stability {s['when']} - {s['label']}" + NL,
         f"preset `{s['preset']}`, method `{s['method']}`, cold={s['cold']}, runs={s['runs']}. "
         f"PASS rule: mean lenient F1 >= 0.80 and (max-min) <= 0.10. **{'PASS' if s['pass'] else 'FAIL'}** "
         f"(spread {s['spread_lenient']})." + NL,
         "| metric | mean | min | max | std |" + NL + "|---|---|---|---|---|"]
    for k, n in (("strict", "strict macro-F1 (all docs, needs_ocr counted as miss)"),
                 ("lenient", "lenient macro-F1 (all docs)"),
                 ("strict_wo_unlinkable", "strict macro-F1 without unlinkable docs"),
                 ("lenient_wo_unlinkable", "lenient macro-F1 without unlinkable docs"),
                 ("wall_s", "wall time per run (s)")):
        v = s[k]
        L.append(f"| {n} | {v['mean']} | {v['min']} | {v['max']} | {v['std']} |")
    L.append(NL + "| run | wall s | strict | lenient | lenient w/o unlinkable | topics |" + NL + "|---|---|---|---|---|---|")
    for r in s["per_run"]:
        L.append(f"| {r['run']} | {r['wall_s']} | {r['strict_f1']} | {r['lenient_f1']} | {r['lenient_f1_wo_unlinkable']} | {'; '.join(r['topics'])} |")
    return NL.join(L) + NL


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=str(ROOT / "corpus" / "gold.csv"))
    ap.add_argument("--db", default=str(store.DB_PATH))
    ap.add_argument("--label", default="run")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--corpus", default=None, help=r"folder with the files named in the gold CSV (env DOCMAP_CORPUS_DIR; default corpus\raw)")
    ap.add_argument("--md-dir", default=None, help=r"converted Markdown folder (env DOCMAP_MD_DIR; default data\md)")
    ap.add_argument("--cache-dir", default=None, help="embedding, LLM answer and token caches (env DOCMAP_CACHE_DIR)")
    ap.add_argument("--scratch-dir", default=None, help="stability-run DBs (env DOCMAP_SCRATCH_DIR)")
    ap.add_argument("--notes-dir", default=None, help="metrics.json, eval-report.md, blind map (env DOCMAP_NOTES_DIR)")
    ap.add_argument("--runs", type=int, default=0, help="stability: run the pipeline N times and report mean/min/max/std")
    ap.add_argument("--cold", action="store_true", help="with --runs: bypass LLM profile/theme caches")
    ap.add_argument("--preset", default=None, choices=["nim", "local"])
    ap.add_argument("--method", default="induce", choices=["induce", "cluster"])
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--blind", action="store_true",
                    help="with --runs: run on neutral file names (doc-01.pdf ...) so theme codes in names cannot leak")
    a = ap.parse_args()
    configure(a.corpus, a.md_dir, a.cache_dir, a.scratch_dir, a.notes_dir)
    if a.runs:
        lab = a.label if a.label != "run" else f"{a.preset or 'nim'}-{a.method}"
        summ = stability(a.runs, a.preset, a.method, a.cold, Path(a.gold), lab, a.digest, a.blind)
        sec = stability_section(summ)
        print(sec)
        if not a.no_write:
            mj = NOTES / "metrics.json"
            try:
                allm = json.loads(mj.read_text(encoding="utf-8"))
            except Exception:
                allm = {}
            st = allm.get("stability") if isinstance(allm.get("stability"), dict) else {}
            st[lab] = summ
            allm["stability"] = st
            mj.write_text(json.dumps(allm, indent=1), encoding="utf-8")
            with open(NOTES / "eval-report.md", "a", encoding="utf-8") as f:
                f.write(sec)
        return
    res = evaluate(Path(a.gold), a.db)
    res["label"] = a.label
    sec = report_section(res, a.label)
    print(sec)
    if not a.no_write:
        mj = NOTES / "metrics.json"
        try:
            allm = json.loads(mj.read_text(encoding="utf-8"))
        except Exception:
            allm = {}
        allm[a.label] = res
        allm["latest"] = res
        mj.write_text(json.dumps(allm, indent=1), encoding="utf-8")
        with open(NOTES / "eval-report.md", "a", encoding="utf-8") as f:
            f.write(sec)


if __name__ == "__main__":
    main()
