"""LLM-native theme induction (TopicGPT-style): one call proposes the themes from ALL document profiles,
a second step assigns each document, and an embedding check lowers the confidence on disagreement.

Deterministic by design: temperature 0, fixed seed, and every LLM answer is cached by
(model, prompt version, sha of prompt). Cold runs (Models.cold) bypass those caches.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .chunk import Chunk
from .link import DocLink
from .llm import Models, doc_block, guard
from .topics import Topic

THEMES_VERSION = "themes-v3"
ASSIGN_VERSION = "assign-v2"
MIN_THEMES, MAX_THEMES = 4, 7
BATCH = 8
EMB_TAU = 0.05        # softmax temperature on centred profile-vs-theme similarity
LLM_W = 0.6           # weight of the LLM confidence in the final confidence
DISAGREE_FACTOR = 0.6  # multiplier when the embedding's top theme differs from the LLM's primary
TOP_N = 3

THEMES_SYSTEM = guard(
    "You design the business-theme list for one organisation's document library. You get short profiles "
    "of ALL its documents. Propose between {lo} and {hi} themes. Rules: "
    "(1) each theme is a business function or area of work that the organisation's staff would recognise: "
    "think of the organisation chart (functions such as finance, people and HR, digital and IT, operations, "
    "risk and regulation, plus the organisation's own core subject areas), not only of the subject matter of "
    "the data. Group documents by the job they do for the organisation, for example money, budgets and accounts "
    "documents belong to a finance theme even when their subject matter is the organisation's core field; "
    "(2) themes are mutually exclusive: a document should have one clear home; "
    "(3) themes are never about file formats or document types (no 'spreadsheets', 'reports', 'presentations'); "
    "(4) no catch-all theme such as 'General', 'Other' or 'Organisational matters'; "
    "(5) each theme should be supported by at least 2 documents where possible; "
    "(6) names are 2 to 5 words and specific. "
    'Answer with strict JSON only: {{"themes": [{{"name": "...", "description": "one sentence, max 30 words, '
    'what the theme covers", "synonyms": ["4 to 8 related terms"]}}]}}'
)

ASSIGN_SYSTEM = guard(
    "You file documents under business themes. For each numbered document pick the PRIMARY theme that best "
    "fits what the document is mainly about. Optionally pick a SECONDARY theme if the document clearly also "
    "belongs there, otherwise null. Use theme names exactly as given. Give confidence from 0 to 1 for the "
    'primary choice. Answer with strict JSON only: {"assignments": [{"doc": 1, "primary": "...", '
    '"secondary": null, "confidence": 0.9}]}'
)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def propose_themes(models: Models, texts: dict[str, str], lo: int = MIN_THEMES, hi: int = MAX_THEMES) -> list[dict]:
    """ONE LLM call over every doc profile. Returns [{name, description, synonyms}]."""
    user = "Document profiles:\n" + "\n".join(doc_block(str(i), texts[d]) for i, d in enumerate(sorted(texts), 1))
    d = models.cached_json(THEMES_VERSION, THEMES_SYSTEM.format(lo=lo, hi=hi), user, max_tokens=1500)
    raw = d.get("themes") if isinstance(d, dict) else d
    out, seen = [], set()
    for t in raw or []:
        name = str(t.get("name", "")).strip()
        if not name or _norm(name) in seen:
            continue
        seen.add(_norm(name))
        syn = t.get("synonyms") or []
        if isinstance(syn, str):
            syn = [x.strip() for x in syn.split(",")]
        out.append({"name": name, "description": str(t.get("description", "")).strip(),
                    "synonyms": [str(x).strip() for x in syn if str(x).strip()][:8]})
    if len(out) < 2:
        raise RuntimeError("theme induction returned fewer than 2 themes")
    return out[:hi]


def _match_theme(name, names: list[str]) -> int | None:
    if name is None:
        return None
    n = _norm(str(name))
    for i, t in enumerate(names):
        if _norm(t) == n:
            return i
    for i, t in enumerate(names):
        if n and (n in _norm(t) or _norm(t) in n):
            return i
    return None


def assign_docs(models: Models, themes: list[dict], texts: dict[str, str], batch: int = BATCH) -> dict[str, dict]:
    """LLM assignment in batches. Returns {doc: {primary: idx|None, secondary: idx|None, conf: float}}."""
    names = [t["name"] for t in themes]
    tl = "\n".join(f"- {t['name']}: {t['description']}" for t in themes)
    docs = sorted(texts)
    parts = [docs[i:i + batch] for i in range(0, len(docs), batch)]

    def run(part: list[str]):
        user = f"Themes:\n{tl}\n\nDocuments:\n" + "\n".join(doc_block(str(i), texts[d]) for i, d in enumerate(part, 1))
        try:
            r = models.cached_json(ASSIGN_VERSION, ASSIGN_SYSTEM, user, max_tokens=900)
        except Exception:
            return part, []
        return part, (r.get("assignments") if isinstance(r, dict) else r) or []

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for part, items in ex.map(run, parts):
            for a in items:
                try:
                    d = part[int(a.get("doc")) - 1]
                except (TypeError, ValueError, IndexError):
                    continue
                p = _match_theme(a.get("primary"), names)
                if p is None:
                    continue
                s = _match_theme(a.get("secondary"), names)
                try:
                    c = float(a.get("confidence", 0.7))
                except (TypeError, ValueError):
                    c = 0.7
                out[d] = {"primary": p, "secondary": s if s != p else None, "conf": min(max(c, 0.0), 1.0)}
    return out


def induce_and_link(models: Models, chunks: list[Chunk], Xraw: np.ndarray, doc_ids: list[str], P: np.ndarray,
                    Praw_texts: dict[str, str], mu_p: np.ndarray, chunk_doc: list[str],
                    lo: int = MIN_THEMES, hi: int = MAX_THEMES):
    """P: centred+normalised profile vectors aligned with doc_ids. Returns (topics, links, info)."""
    themes = propose_themes(models, Praw_texts, lo, hi)
    assign = assign_docs(models, themes, Praw_texts)
    ttexts = [f"{t['name']}: {t['description']} Synonyms: {', '.join(t['synonyms'])}" for t in themes]
    raw = models.embed(ttexts, "passage")
    cen = raw - mu_p
    cen = cen / np.maximum(np.linalg.norm(cen, axis=1, keepdims=True), 1e-9)

    sims = P @ cen.T                                     # (docs, themes)
    z = sims / EMB_TAU
    pe = np.exp(z - z.max(axis=1, keepdims=True))
    pe /= pe.sum(axis=1, keepdims=True)
    emb_top = pe.argmax(axis=1)
    di = {d: i for i, d in enumerate(doc_ids)}

    # final primary per doc: LLM choice; fall back to the embedding top if the LLM gave none
    primary: dict[str, int] = {}
    for d in doc_ids:
        primary[d] = assign[d]["primary"] if d in assign else int(emb_top[di[d]])
    used = sorted(set(primary.values()))
    keep = {k: j for j, k in enumerate(used)}          # drop themes no doc picked
    members_docs: dict[int, set[str]] = {k: set() for k in keep}
    for d, k in primary.items():
        members_docs[k].add(d)

    topics: list[Topic] = []
    for k in used:
        idx = [di[d] for d in sorted(members_docs[k])]
        c = P[idx].mean(axis=0)
        c = c / max(np.linalg.norm(c), 1e-9)
        t = Topic(themes[k]["name"], themes[k]["description"], themes[k]["synonyms"],
                  [j for j, dd in enumerate(chunk_doc) if dd in members_docs[k]])
        t.emb, t.centroid = cen[k], c
        t.extra["raw_emb"] = raw[k]
        topics.append(t)

    by_doc: dict[str, list[int]] = {}
    for i, ch in enumerate(chunks):
        by_doc.setdefault(ch.doc_id, []).append(i)
    R = np.stack([t.extra["raw_emb"] for t in topics])
    links: list[DocLink] = []
    n_disagree = 0
    for d in doc_ids:
        i = di[d]
        a = assign.get(d)
        pk = primary[d]
        llm_c = a["conf"] if a else 0.3
        agree = int(emb_top[i]) == pk
        e_p = float(pe[i, pk])
        conf = LLM_W * llm_c + (1 - LLM_W) * e_p
        if not agree:
            conf *= DISAGREE_FACTOR
            n_disagree += 1
        conf = round(min(conf, 0.99), 4)
        idx = by_doc.get(d, [])
        S = Xraw[idx] @ R.T if idx else np.zeros((0, len(topics)))

        def evidence(tk: int, role: str, c_llm, p_emb):
            note = (f"{role}; LLM confidence {c_llm:.2f}; embedding probability {p_emb:.2f}; "
                    f"embedding {'agrees' if agree else 'DISAGREES (top theme: ' + themes[int(emb_top[i])]['name'] + ')'}")
            ev = [{"chunk": None, "heading": "(AI theme decision)", "snippet": note, "sim": round(float(sims[i, used[tk]]), 4)},
                  {"chunk": None, "heading": "(document profile)", "snippet": Praw_texts[d][:240], "sim": round(float(sims[i, used[tk]]), 4)}]
            if len(idx):
                for j in np.argsort(-S[:, tk])[:TOP_N]:
                    ev.append({"chunk": int(idx[j]), "heading": chunks[idx[j]].heading_path,
                               "snippet": chunks[idx[j]].text[:240].replace(chr(10), " "), "sim": round(float(S[j, tk]), 4)})
            return ev

        tk = keep[pk]
        links.append(DocLink(d, tk, round(float(sims[i, pk]), 4), conf, evidence(tk, "primary", llm_c, e_p)))
        links[-1].role, links[-1].disagreement = "primary", not agree
        # secondary theme from the LLM (kept below the primary confidence)
        sk = a["secondary"] if a else None
        if sk is not None and sk in keep:
            sc = round(min(conf * 0.5, 0.45), 4)
            lk = DocLink(d, keep[sk], round(float(sims[i, sk]), 4), sc, evidence(keep[sk], "secondary", llm_c, float(pe[i, sk])))
            lk.role, lk.disagreement = "secondary", False
            links.append(lk)
        # when the embedding disagrees, also offer its theme as an alternative for the reviewer
        ek = int(emb_top[i])
        if not agree and ek in keep and ek != sk:
            ac = round(min(float(pe[i, ek]) * 0.5, conf * 0.9), 4)
            lk = DocLink(d, keep[ek], round(float(sims[i, ek]), 4), ac, evidence(keep[ek], "alternative (embedding)", llm_c, float(pe[i, ek])))
            lk.role, lk.disagreement = "alternative", True
            links.append(lk)

    info = {"method": "induce", "themes_proposed": [t["name"] for t in themes],
            "themes_kept": [t.name for t in topics], "docs_llm_assigned": len(assign), "docs": len(doc_ids),
            "n_disagree": n_disagree, "algo": "induce", "k": len(topics), "silhouette": None,
            "clusters_before_merge": len(themes), "topics_after_merge": len(topics)}
    return topics, links, info
