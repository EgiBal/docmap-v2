import numpy as np
from sqlmodel import Session, select

from docmap import store
from docmap.chunk import chunk_markdown, clean_title
from docmap.eval import hungarian_map, score
from docmap.llm import strip_fences, parse_json
from docmap.tokens import count


def _vec(i, d=8):
    v = np.zeros(d, dtype=np.float32)
    v[i] = 1.0
    return v


def _run(eng, topic_names, links, vecs=None):
    vecs = vecs or [_vec(i) for i in range(len(topic_names))]
    topics = [{"name": n, "description": "", "synonyms": [], "embedding": v, "centroid": v}
              for n, v in zip(topic_names, vecs)]
    docs = [{"id": "a.pdf", "format": "pdf", "status": "ok", "tokens": 1}, {"id": "b.pdf", "format": "pdf", "status": "ok", "tokens": 1}]
    return store.save_run(eng, preset="t", params={}, timings={}, docs=docs, chunks=[], topics=topics,
                          links=[{"doc_id": d, "topic": t, "score": .5, "confidence": c, "evidence": []} for d, t, c in links])


def test_human_edits_survive_rerun():
    eng = store.get_engine(":memory:")
    r1 = _run(eng, ["Finance", "HR"], [("a.pdf", 0, .9), ("b.pdf", 1, .8)])
    fin, hr = r1["topic_ids"]
    store.human_set_link(eng, "a.pdf", fin, "moved", moved_to=hr)
    store.human_set_link(eng, "b.pdf", hr, "rejected")
    # re-run: AI now proposes the opposite
    r2 = _run(eng, ["Finance", "HR"], [("a.pdf", 0, .99), ("b.pdf", 1, .99)])
    assert r2["topic_ids"] == [fin, hr]          # ids are stable
    with Session(eng) as s:
        links = {(l.doc_id, l.topic_id): l for l in s.exec(select(store.Link)).all()}
    assert links[("a.pdf", fin)].status == "moved" and links[("a.pdf", fin)].source == "human"
    assert links[("a.pdf", fin)].moved_to == hr
    assert links[("a.pdf", hr)].status == "accepted" and links[("a.pdf", hr)].source == "human"
    assert links[("b.pdf", hr)].status == "rejected" and links[("b.pdf", hr)].source == "human"
    assert r2["kept_human"] == 3
    assert all(l.source == "human" for l in links.values() if l.doc_id == "a.pdf" or l.topic_id == hr)


def test_topic_ids_follow_embedding_similarity_not_order():
    eng = store.get_engine(":memory:")
    r1 = _run(eng, ["Finance", "HR"], [("a.pdf", 0, .9)])
    r2 = _run(eng, ["HR v2", "Finance v2"], [("a.pdf", 1, .9)], vecs=[_vec(1), _vec(0)])
    assert r2["topic_ids"] == [r1["topic_ids"][1], r1["topic_ids"][0]]


def test_unmatched_old_topic_is_deactivated_new_gets_new_id():
    eng = store.get_engine(":memory:")
    r1 = _run(eng, ["Finance"], [("a.pdf", 0, .9)])
    r2 = _run(eng, ["Totally new"], [("a.pdf", 0, .9)], vecs=[_vec(5)])
    assert r2["topic_ids"][0] != r1["topic_ids"][0]
    with Session(eng) as s:
        assert s.get(store.Topic, r1["topic_ids"][0]).active is False


def test_hungarian_toy():
    # topics 0..2 x gold 0..1; topic 2 is a split that stays unmatched
    ov = np.array([[5, 0], [1, 4], [2, 0]])
    assert hungarian_map(ov) == {0: 0, 1: 1}


def test_score_strict_vs_lenient():
    gold = {"d1": ("A", ""), "d2": ("B", "A"), "d3": ("B", "")}
    pred = {"d1": "A", "d2": "A", "d3": "A"}
    s = score(pred, gold, ["A", "B"])
    assert s["strict"]["accuracy"] == round(1 / 3, 3)
    assert s["lenient"]["accuracy"] == round(2 / 3, 3)
    assert s["strict"]["per_theme"]["A"]["tp"] == 1 and s["strict"]["per_theme"]["A"]["fp"] == 2


def test_chunker_boundaries():
    md = "# Title\nintro line\n\n## Sec A\n" + "\n".join(f"line {i} " + "word " * 20 for i in range(60)) + "\n\n## Sec B\nshort tail text here"
    ch = chunk_markdown("doc.pdf", md, target=200, min_tokens=0)
    assert all(c.tokens <= 200 + 5 for c in ch)
    assert ch[0].heading_path == "Title" and "intro line" in ch[0].text
    paths = {c.heading_path for c in ch}
    assert "Title > Sec A" in paths and "Title > Sec B" in paths
    assert [c.idx for c in ch] == list(range(len(ch)))
    # nothing lost: every numbered line appears exactly once
    body = "\n".join(c.text for c in ch)
    assert all(f"line {i} " in body for i in range(60))
    # headings inside code fences do not split
    fenced = chunk_markdown("d", "# A\n```\n# not a heading\n```\ntext")
    assert len(fenced) == 1 and "# not a heading" in fenced[0].text


def test_chunker_merges_tiny_and_cuts_long_line():
    ch = chunk_markdown("d", "# A\nx\n\n# B\ny", min_tokens=40)
    assert len(ch) == 1
    long = "# A\n" + "word " * 2000
    parts = chunk_markdown("d", long, target=300)
    assert len(parts) >= 6 and all(p.tokens <= 305 for p in parts)


def test_llm_json_helpers():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure: {"a": 2} done') == {"a": 2}
    assert strip_fences("```\nx\n```") == "x"


def test_clean_title():
    assert clean_title("fin-01-ea-annual-report-2024-25.pdf") == "ea annual report 2024 25"
    assert count("hello") == 1
