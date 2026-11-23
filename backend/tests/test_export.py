import json
import zipfile

import numpy as np

from docmap import store
from docmap.export import export_pack


def _vec(i, d=8):
    v = np.zeros(d, dtype=np.float32)
    v[i] = 1.0
    return v


def _build(tmp_path, big=False):
    md_dir = tmp_path / "md"
    md_dir.mkdir()
    texts = {
        "a.docx": "# A\n\nalpha text\n",
        "b.pdf": "# B\n\nbeta text\n",
        "c.xlsx": "# C\n\n" + "\n".join(f"| row{i} | {i*7} |" for i in range(3000)) + "\n",
        "d.pdf": "# D\n\ndelta text\n",
        "e.docx": "# E\n\nepsilon text\n",
    }
    if big:
        texts["big.pdf"] = "# Big\n\n" + "lorem ipsum dolor " * 50000
    for k, v in texts.items():
        (md_dir / f"{k}.md".replace(".docx.md", ".docx.md")).write_text(v, encoding="utf-8")
    # md files are named <doc id>.md
    eng = store.get_engine(tmp_path / "t.db")
    topics = [{"name": n, "description": f"about {n}", "synonyms": [n + " syn"], "embedding": _vec(i),
               "centroid": _vec(i)} for i, n in enumerate(["Waste", "Flood Risk", "Empty topic"])]
    docs = [{"id": k, "format": k.split(".")[-1], "status": "ok", "tokens": 1, "token_count": 0} for k in texts]
    docs.append({"id": "scan.pdf", "format": "pdf", "status": "needs_ocr", "tokens": 0})
    docs.append({"id": "orphan.pdf", "format": "pdf", "status": "ok", "tokens": 1})
    (md_dir / "orphan.pdf.md").write_text("# O\n\norphan\n", encoding="utf-8")
    links = [
        {"doc_id": "a.docx", "topic": 0, "score": .9, "confidence": .9, "evidence": []},
        {"doc_id": "b.pdf", "topic": 0, "score": .8, "confidence": .8, "evidence": []},
        {"doc_id": "c.xlsx", "topic": 1, "score": .7, "confidence": .7, "evidence": []},
        {"doc_id": "d.pdf", "topic": 0, "score": .6, "confidence": .6, "evidence": []},
        {"doc_id": "e.docx", "topic": 1, "score": .5, "confidence": .5, "evidence": []},
    ]
    if big:
        links.append({"doc_id": "big.pdf", "topic": 1, "score": .5, "confidence": .5, "evidence": []})
        docs.append({"id": "big.pdf", "format": "pdf", "status": "ok", "tokens": 1, "token_count": 0})
    info = store.save_run(eng, preset="t", params={}, timings={}, docs=docs, chunks=[], topics=topics, links=links)
    tid = info["topic_ids"]
    store.human_set_link(eng, "a.docx", tid[0], "accepted")            # human-accepted
    store.human_set_link(eng, "b.pdf", tid[0], "rejected")             # rejected
    store.human_set_link(eng, "d.pdf", tid[0], "moved", tid[1])        # moved to Flood Risk
    return tmp_path / "t.db", md_dir, texts


def _run(tmp_path, **kw):
    db, md_dir, texts = _build(tmp_path, big=kw.pop("big", False))
    out = tmp_path / kw.pop("out", "out")
    r = export_pack(db, out, md_dir=md_dir, raw_dir=tmp_path / "noraw", **kw)
    return r, out, texts


def test_rejected_moved_human_ocr(tmp_path):
    r, out, _ = _run(tmp_path)
    names = sorted(p.name for p in out.iterdir())
    assert names == ["00-index.md", "01-waste.md", "02-flood-risk.md"]   # empty topic gets no file
    waste = (out / "01-waste.md").read_text(encoding="utf-8")
    flood = (out / "02-flood-risk.md").read_text(encoding="utf-8")
    assert "## b.pdf" not in waste and "## b.pdf" not in flood           # rejected never exported
    assert "## d.pdf" in flood and "## d.pdf" not in waste               # moved goes to new topic
    assert "| a.docx | docx | " in waste and "accepted ✓" in waste        # human-accepted marked
    assert "topic: \"Waste\"" in waste and "doc_count: 1" in waste and "token_count:" in waste
    assert "How to use this pack" in waste
    idx = (out / "00-index.md").read_text(encoding="utf-8")
    assert "## Needs OCR (not included)\n\n- scan.pdf" in idx
    assert "## Unassigned\n\n- b.pdf\n- orphan.pdf" in idx               # rejected + unlinked docs
    assert "| 01-waste.md | Waste | 1 |" in idx
    assert r.per_topic_tokens["01-waste.md"] > 0


def test_accepted_only(tmp_path):
    r, out, _ = _run(tmp_path, statuses=("accepted",))
    # only human-accepted links (a.docx at Waste, d.pdf at Flood Risk) survive
    assert sorted(p.name for p in out.iterdir()) == ["00-index.md", "01-waste.md", "02-flood-risk.md"]
    flood = (out / "02-flood-risk.md").read_text(encoding="utf-8")
    assert "## c.xlsx" not in flood and "## d.pdf" in flood


def test_zip_equals_folder_and_no_truncation(tmp_path):
    r1, out1, texts = _run(tmp_path, out="folder")
    r2 = export_pack(tmp_path / "t.db", tmp_path / "zipout", md_dir=tmp_path / "md",
                     raw_dir=tmp_path / "noraw", fmt="zip")
    zp = r2.paths[0]
    assert zp.endswith(".zip") and "docmap-pack-" in zp
    with zipfile.ZipFile(zp) as z:
        zipped = {n: z.read(n).decode("utf-8") for n in z.namelist()}
    folder = {p.name: p.read_text(encoding="utf-8") for p in out1.iterdir()}
    # generated_at may differ by a second between the two runs: compare without it
    strip = lambda d: {k: "\n".join(l for l in v.splitlines() if not l.startswith("generated_at:")) for k, v in d.items()}
    assert strip(zipped) == strip(folder)
    # long doc fully present
    flood = folder["02-flood-risk.md"]
    assert texts["c.xlsx"].strip() in flood and "| row2999 | 20993 |" in flood


def test_big_topic_warning(tmp_path):
    r, out, _ = _run(tmp_path, big=True)
    assert any("02-flood-risk.md" in w for w in r.warnings)
    flood = (out / "02-flood-risk.md").read_text(encoding="utf-8")
    assert "WARNING" in flood.split("\n---\n")[1][:600] or "size_warning" in flood[:1500]
    assert flood.count("lorem ipsum dolor") == 50000                     # nothing cut
    assert "## Warnings" in (out / "00-index.md").read_text(encoding="utf-8")
    assert r.per_topic_tokens["02-flood-risk.md"] > 128_000
