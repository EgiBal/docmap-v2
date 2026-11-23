import json

import numpy as np
from sqlalchemy import text
from sqlmodel import Session, select

from docmap import store
from docmap.induce import _match_theme, assign_docs, propose_themes
from docmap.llm import JsonCache


class FakeModels:
    def __init__(self, tmp_path, answers):
        self.answers = answers
        self.jcache = JsonCache(tmp_path / "j.sqlite")
        self.cold = False
        self.calls = 0
        self.cfg = {"LLM_MODEL": "fake"}
        self.stats = {"llm_cached": 0}

    def chat_json(self, system, user, max_tokens=700, temperature=0.0):
        self.calls += 1
        return self.answers.pop(0)

    cached_json = __import__("docmap.llm", fromlist=["Models"]).Models.cached_json


def test_match_theme_exact_and_fuzzy():
    names = ["Finance and Budget", "Workforce Diversity"]
    assert _match_theme("finance and budget", names) == 0
    assert _match_theme("Workforce", names) == 1
    assert _match_theme("Nonsense", names) is None
    assert _match_theme(None, names) is None


def test_propose_dedupes_and_caches(tmp_path):
    ans = {"themes": [{"name": "A theme", "description": "d", "synonyms": "x, y"},
                      {"name": "a  theme", "description": "dup"}, {"name": "B theme", "description": "d"}]}
    m = FakeModels(tmp_path, [ans])
    out = propose_themes(m, {"d1": "one", "d2": "two"})
    assert [t["name"] for t in out] == ["A theme", "B theme"] and out[0]["synonyms"] == ["x", "y"]
    propose_themes(m, {"d1": "one", "d2": "two"})       # same prompt: served from cache
    assert m.calls == 1
    m.cold = True
    m.answers.append(ans)
    propose_themes(m, {"d1": "one", "d2": "two"})       # cold bypasses the cache
    assert m.calls == 2


def test_assign_docs_parses_and_ignores_bad_rows(tmp_path):
    themes = [{"name": "Finance", "description": ""}, {"name": "HR", "description": ""}]
    ans = {"assignments": [{"doc": 1, "primary": "Finance", "secondary": "HR", "confidence": 0.9},
                           {"doc": 2, "primary": "HR", "secondary": "HR", "confidence": "x"},
                           {"doc": 9, "primary": "HR"}, {"doc": 2, "primary": "zzz"}]}
    m = FakeModels(tmp_path, [ans])
    out = assign_docs(m, themes, {"a": "t1", "b": "t2"})
    assert out["a"] == {"primary": 0, "secondary": 1, "conf": 0.9}
    assert out["b"]["primary"] == 1 and out["b"]["secondary"] is None and out["b"]["conf"] == 0.7


def test_size_warning_thresholds():
    assert store.size_warning(1000) is None
    assert "128k" in store.size_warning(200_000) and "200,000" in store.size_warning(200_000)
    assert "32k" in store.size_warning(50_000)


def test_migration_adds_columns_and_keeps_rows(tmp_path):
    db = tmp_path / "old.db"
    import sqlite3
    c = sqlite3.connect(db)
    c.execute("create table document (id text primary key, format text, status text, tokens integer, note text, updated_at text)")
    c.execute("insert into document values ('a.pdf','pdf','ok',5,'','2026-01-01')")
    c.commit()
    c.close()
    eng = store.get_engine(db)
    with Session(eng) as s:
        d = s.get(store.Document, "a.pdf")
    assert d.tokens == 5 and d.token_count == 0 and d.size_warning is None
    with eng.begin() as cx:
        assert cx.execute(text("select count(*) from link")).scalar() == 0


def test_save_run_stores_token_count_and_link_role():
    eng = store.get_engine(":memory:")
    v = np.eye(4, dtype=np.float32)
    docs = [{"id": "a.pdf", "format": "pdf", "status": "ok", "tokens": 200_000, "token_count": 200_000,
             "size_warning": store.size_warning(200_000)}]
    store.save_run(eng, preset="t", params={}, timings={}, docs=docs, chunks=[],
                   topics=[{"name": "T", "description": "", "synonyms": [], "embedding": v[0], "centroid": v[0]}],
                   links=[{"doc_id": "a.pdf", "topic": 0, "score": .5, "confidence": .5, "evidence": [],
                           "role": "alternative", "disagreement": True}])
    with Session(eng) as s:
        assert s.get(store.Document, "a.pdf").size_warning
        l = s.exec(select(store.Link)).one()
    assert l.role == "alternative" and l.disagreement is True
