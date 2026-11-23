"""T16c: topic-pack metric, configurable folders for eval/pipeline."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from docmap import api, eval as ev, llm, paths, pipeline
from tests.test_api import client  # noqa: F401  (fixture)
from docmap.paths import ROOT


def _d(i, t):
    return SimpleNamespace(id=i, token_count=t, status="ok", format="pdf", note="")


def test_pack_stats_median_against_library(monkeypatch):
    monkeypatch.setattr(api, "_tokens", lambda d: d.token_count)
    docs = [_d("a", 10), _d("b", 20), _d("c", 970)]
    L = lambda doc, topic, st="proposed": SimpleNamespace(doc_id=doc, topic_id=topic, status=st)  # noqa: E731
    links = [L("a", 1), L("b", 1), L("c", 2), L("c", 3, "rejected"), L("a", 3, "moved")]
    r = api._pack_stats(docs, links, 1000)
    assert r["n_topics"] == 2 and r["median_tokens"] == 500 and r["largest_tokens"] == 970
    assert r["median_saved_pct"] == 50.0 and r["library_tokens"] == 1000


def test_pack_stats_empty():
    assert api._pack_stats([], [], 0)["median_saved_pct"] == 0.0


def test_metrics_has_pack_and_keeps_negative_saving(client):  # noqa: F811
    m = client.get("/api/metrics").json()
    assert set(m["pack"]) >= {"median_tokens", "median_saved_pct", "library_tokens", "n_topics"}
    d = client.get("/api/documents/a.pdf").json()
    assert "saved_pct" in d["tokens"]   # raw value; the UI shows the sign (never clamped)


def test_eval_configure_sets_all_folders(monkeypatch, tmp_path):
    for v in ("DOCMAP_CORPUS_DIR", "DOCMAP_MD_DIR", "DOCMAP_CACHE_DIR", "DOCMAP_SCRATCH_DIR", "DOCMAP_NOTES_DIR"):
        monkeypatch.setenv(v, os.environ.get(v, ""))      # so monkeypatch restores them
    for mod, names in ((ev, ["NOTES", "RAW", "MD_DIR", "TOK_CACHE", "SCRATCH"]), (pipeline, ["MD_DIR", "META", "TOK_CACHE"])):
        for n in names:
            monkeypatch.setattr(mod, n, getattr(mod, n))
    ev.configure(corpus=tmp_path / "blind", md_dir=tmp_path / "md", cache_dir=tmp_path / "cache",
                 scratch_dir=tmp_path / "scr", notes_dir=tmp_path / "notes")
    assert ev.RAW == (tmp_path / "blind").resolve() and ev.MD_DIR == (tmp_path / "md").resolve()
    assert ev.SCRATCH == (tmp_path / "scr").resolve() and ev.NOTES == (tmp_path / "notes").resolve()
    assert ev.TOK_CACHE == (tmp_path / "cache").resolve() / "doc_tokens.json"
    assert pipeline.MD_DIR == ev.MD_DIR and pipeline.META == ev.MD_DIR / "_meta.json"
    assert pipeline.TOK_CACHE == (tmp_path / "cache").resolve() / "md_tokens.json"
    # the LLM caches follow the same cache dir
    c = llm.JsonCache()
    assert (tmp_path / "cache" / "llm.sqlite").exists()
    c.db.close()


def test_defaults_are_todays_paths(monkeypatch):
    for v in ("DOCMAP_CORPUS_DIR", "DOCMAP_MD_DIR", "DOCMAP_CACHE_DIR", "DOCMAP_SCRATCH_DIR", "DOCMAP_NOTES_DIR"):
        monkeypatch.delenv(v, raising=False)
    assert paths.corpus_dir() == ROOT / "corpus" / "raw"
    assert paths.cache_dir() == ROOT / "data" / "cache"
    assert paths.scratch_dir() == ROOT / "data" / "scratch"


def test_cli_flags_exist():
    import subprocess, sys
    for mod in ("docmap.eval", "docmap.pipeline"):
        out = subprocess.run([sys.executable, "-m", mod, "--help"], capture_output=True, text=True).stdout
        assert "--md-dir" in out and "--cache-dir" in out
    out = subprocess.run([sys.executable, "-m", "docmap.eval", "--help"], capture_output=True, text=True).stdout
    assert "--corpus" in out and "--scratch-dir" in out
