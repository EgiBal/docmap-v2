import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from docmap import api, store
from docmap.store import Link


def _vec(i, d=8):
    v = np.zeros(d, dtype=np.float32)
    v[i] = 1.0
    return v


@pytest.fixture()
def client(tmp_path):
    db = tmp_path / "t.db"
    eng = store.get_engine(db)
    topics = [{"name": n, "description": f"{n} desc", "synonyms": ["x"], "embedding": _vec(i), "centroid": _vec(i)}
              for i, n in enumerate(["Finance", "HR", "Risk"])]
    docs = [{"id": "a.pdf", "format": "pdf", "status": "ok", "tokens": 100, "note": ""},
            {"id": "b.xlsx", "format": "xlsx", "status": "ok", "tokens": 250_000, "note": ""},
            {"id": "c.pdf", "format": "pdf", "status": "needs_ocr", "tokens": 0, "note": "scan"}]
    ev = [{"chunk": None, "heading": "h", "snippet": "money talk", "sim": 0.5}]
    links = [{"doc_id": "a.pdf", "topic": 0, "score": .5, "confidence": .9, "evidence": ev},
             {"doc_id": "b.xlsx", "topic": 1, "score": .5, "confidence": .3, "evidence": ev},
             {"doc_id": "b.xlsx", "topic": 2, "score": .4, "confidence": .6, "evidence": ev}]
    store.save_run(eng, preset="t", params={}, timings={"total": 1}, docs=docs, chunks=[], topics=topics, links=links)
    eng.dispose()
    api.configure(db=db, upload_dir=tmp_path / "up", md_dir=tmp_path / "md")
    (tmp_path / "md").mkdir()
    (tmp_path / "md" / "a.pdf.md").write_text("# Hello\n\ntext", encoding="utf-8")
    return TestClient(api.app, headers={"X-DocMap": "1"})


def test_lists(client):
    m = client.get("/api/metrics").json()
    assert m["docs"] == 3 and m["topics"] == 3 and m["open_reviews"] == 3 and m["size_warnings"] == 1
    assert len(client.get("/api/topics").json()) == 3
    docs = {d["id"]: d for d in client.get("/api/documents").json()}
    assert docs["b.xlsx"]["size_warning"] and docs["c.pdf"]["status"] == "needs_ocr"
    assert docs["b.xlsx"]["top_topic"]["name"] == "Risk"
    d = client.get("/api/documents/a.pdf").json()
    assert "Hello" in d["markdown"] and d["links"][0]["evidence"][0]["snippet"] == "money talk"
    assert client.get("/api/documents/zzz").status_code == 404
    g = client.get("/api/graph").json()
    assert len(g["nodes"]) == 6 and len(g["edges"]) == 3
    r = client.get("/api/review").json()
    assert [x["confidence"] for x in r] == sorted(x["confidence"] for x in r)


def _link(client, doc, topic):
    return next(x for x in client.get("/api/review").json() if x["doc_id"] == doc and x["topic_name"] == topic)


def test_accept_reject_persist(client):
    lid = _link(client, "a.pdf", "Finance")["id"]
    assert client.patch(f"/api/links/{lid}", json={"action": "accept"}).json()["link"]["status"] == "accepted"
    rid = _link(client, "b.xlsx", "HR")["id"]
    client.patch(f"/api/links/{rid}", json={"action": "reject"})
    with Session(api.eng()) as s:
        a, r = s.get(store.Link, lid), s.get(store.Link, rid)
        assert (a.status, a.source, a.reviewed_at is not None) == ("accepted", "human", True)
        assert (r.status, r.source) == ("rejected", "human")
    assert client.get("/api/metrics").json()["open_reviews"] == 1


def test_move(client):
    lid = _link(client, "b.xlsx", "HR")["id"]
    topics = {t["name"]: t["id"] for t in client.get("/api/topics").json()}
    assert client.patch(f"/api/links/{lid}", json={"action": "move"}).status_code == 422
    res = client.patch(f"/api/links/{lid}", json={"action": "move", "topic_id": topics["Finance"]}).json()
    assert res["link"]["status"] == "moved"
    with Session(api.eng()) as s:
        new = s.exec(select(store.Link).where(store.Link.doc_id == "b.xlsx",
                                              store.Link.topic_id == topics["Finance"])).one()
        assert (new.status, new.source) == ("accepted", "human")


def test_upload(client, tmp_path):
    r = client.post("/api/upload", files=[("files", ("x.docx", b"abc")), ("files", ("y.txt", b"no"))]).json()
    assert r["saved"] == ["x.docx"] and r["skipped"] == ["y.txt"]
    assert (tmp_path / "up" / "x.docx").exists()
    assert client.get("/api/process/status").json()["state"] in ("idle", "running", "done", "error")


def test_export_zip_and_preview(client):
    import io
    import zipfile
    r = client.get("/api/export?fmt=zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.testzip() is None and "00-index.md" in z.namelist()
    p = client.get("/api/export/preview?accepted_only=true").json()
    assert p["topics"] == [] and "limit" in p
    p = client.get("/api/export/preview").json()
    assert p["topics"] and all(t["file"].endswith(".md") for t in p["topics"])
    assert client.get("/api/export?fmt=bogus").status_code == 422


def test_patch_during_run_is_409_with_message(client):
    link_id = client.get("/api/review").json()[0]["id"]
    api._job["state"] = "running"
    try:
        r = client.patch(f"/api/links/{link_id}", json={"action": "accept"})
        assert r.status_code == 409 and "in progress" in r.json()["detail"]
    finally:
        api._job["state"] = "idle"
    assert client.patch(f"/api/links/{link_id}", json={"action": "accept"}).status_code == 200


def test_progress_hook_reaches_status(client, monkeypatch):
    import docmap.pipeline as pl

    def fake(source, preset, db, verbose=False, on_progress=None, _md_dir=None, cold=False):
        for st, d, t in [("convert", 3, 8), ("profile", 2, 8), ("save", 1, 1)]:
            on_progress(st, d, t)
            seen.append(client.get("/api/process/status").json())
        return {"timings": {}, "topics": 1, "n_chunks": 0}

    seen: list = []
    monkeypatch.setattr(pl, "run_pipeline", fake)
    import time as _t
    api._job.update(state="running", started=_t.time(), stage_times={})
    api._run_job(None, api.UPLOAD_DIR)
    assert [s["step"] for s in seen] == ["convert", "profile", "save"]
    assert seen[0]["done"] == 3 and seen[0]["total"] == 8 and 0 < seen[0]["pct"] < seen[1]["pct"] < seen[2]["pct"]
    final = client.get("/api/process/status").json()
    assert final["state"] == "done" and list(final["stage_times"]) == ["convert", "profile", "save"]


def test_review_disagreement_first_and_content_changed_flag(client):
    with Session(api.eng()) as s:
        for l in s.exec(select(Link)).all():
            if l.doc_id == "a.pdf":          # confidence .9 would sort last
                l.disagreement = True
            if l.doc_id == "b.xlsx" and l.topic_id == 2:
                l.content_changed = True
            s.add(l)
        s.commit()
    q = client.get("/api/review").json()
    assert q[0]["doc_id"] == "a.pdf" and q[0]["disagreement"] is True
    assert any(x["content_changed"] for x in q)




