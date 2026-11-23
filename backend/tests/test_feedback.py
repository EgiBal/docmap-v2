import numpy as np
import pytest
from sqlmodel import Session, select

from docmap import feedback, store

VEC = {  # keyword in text -> 3-d vector
    "docA": [1.0, 0.8, 0.0], "docB": [0.9, 0.9, 0.05], "docC": [0.0, 1.0, 0.1], "docD": [0.1, 0.2, 1.0],
    "xtopic": [1.0, 0.7, 0.2], "ytopic": [0.7, 1.0, 0.0], "ztopic": [0.0, 0.2, 1.0],
}


class FakeModels:
    def embed(self, texts, kind="passage"):
        out = []
        for t in texts:
            v = next((np.array(vv, dtype=np.float32) for k, vv in VEC.items() if k in t), np.ones(3, np.float32))
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def _setup(tmp_path):
    eng = store.get_engine(tmp_path / "t.db")
    topics = [{"name": n, "description": "", "synonyms": [], "embedding": np.ones(3, np.float32),
               "centroid": np.ones(3, np.float32)} for n in ("xtopic", "ytopic", "ztopic")]
    docs = [{"id": d, "format": "pdf", "status": "ok", "tokens": 1} for d in ("docA", "docB", "docC", "docD")]
    chunks = [{"doc_id": d["id"], "idx": 0, "heading_path": "", "text": d["id"], "tokens": 1} for d in docs]
    links = [{"doc_id": "docA", "topic": 0, "score": .5, "confidence": .5},
             {"doc_id": "docB", "topic": 0, "score": .5, "confidence": .5},
             {"doc_id": "docC", "topic": 1, "score": .5, "confidence": .6},
             {"doc_id": "docD", "topic": 2, "score": .5, "confidence": .6}]
    r = store.save_run(eng, preset="t", params={}, timings={}, docs=docs, chunks=chunks, topics=topics, links=links)
    return eng, r["topic_ids"], tmp_path / "t.db"


def _conf(eng):
    with Session(eng) as s:
        return {(l.doc_id, l.topic_id): (l.confidence, l.source, l.status) for l in s.exec(select(store.Link)).all()}


def _run(db, **kw):
    return feedback.rescore(db, models=FakeModels(), **kw)


def test_accept_raises_similar_unreviewed(tmp_path):
    eng, (x, y, z), db = _setup(tmp_path)
    before = _conf(eng)[("docB", x)][0]
    store.human_set_link(eng, "docA", x, "accepted")
    res = _run(db)
    after = _conf(eng)[("docB", x)][0]
    assert after > before
    assert res.examples_per_topic[x] == 1 and res.examples_per_topic[y] == 0
    assert any(c[0] and c[3] == x for c in res.changed)


def test_reject_lowers(tmp_path):
    eng, (x, y, z), db = _setup(tmp_path)
    before = _conf(eng)[("docB", x)][0]
    store.human_set_link(eng, "docA", x, "rejected")
    res = _run(db)
    assert _conf(eng)[("docB", x)][0] < before
    assert res.negatives_per_topic[x] == 1


def test_human_links_never_change(tmp_path):
    eng, (x, y, z), db = _setup(tmp_path)
    store.human_set_link(eng, "docA", x, "accepted")
    store.human_set_link(eng, "docC", y, "rejected")
    before = {k: v for k, v in _conf(eng).items() if v[1] == "human"}
    _run(db)
    after = {k: v for k, v in _conf(eng).items() if v[1] == "human"}
    assert before == after and len(before) == 2


def test_dry_run_writes_nothing(tmp_path):
    eng, (x, y, z), db = _setup(tmp_path)
    store.human_set_link(eng, "docA", x, "accepted")
    before = _conf(eng)
    res = _run(db, dry_run=True)
    assert res.changed and res.dry_run
    assert _conf(eng) == before
    _run(db)
    assert _conf(eng) != before


def test_no_reviews_and_no_examples_unchanged(tmp_path):
    eng, (x, y, z), db = _setup(tmp_path)
    before = _conf(eng)
    assert _run(db).changed == []
    assert _conf(eng) == before
    # a review for topic X only: the link of docD to topic Z (no examples, unrelated doc) stays put
    store.human_set_link(eng, "docA", x, "accepted")
    res = _run(db)
    assert res.examples_per_topic[z] == 0
    assert _conf(eng)[("docD", z)][0] == pytest.approx(0.6, abs=0.02)


def test_moved_counts_as_example_for_target(tmp_path):
    eng, (x, y, z), db = _setup(tmp_path)
    store.human_set_link(eng, "docA", x, "moved", moved_to=y)
    res = _run(db)
    assert res.examples_per_topic[y] == 1 and res.negatives_per_topic[x] == 1
