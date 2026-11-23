"""AI-only topic discovery: embed chunks -> cluster -> LLM names each cluster -> merge near-duplicates."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import silhouette_score

from .chunk import Chunk, clean_title
from .llm import Models, doc_block, guard
from .tokens import count

K_MIN, K_MAX = 3, 10
REP_CHUNKS = 6
REP_MAX_TOKENS = 2500
MERGE_SIM = 0.9

SYSTEM = guard(
    "You analyse a business's document collection. You are given excerpts from one cluster of "
    "similar passages. Name the BUSINESS THEME they share (for example 'Financial reporting and "
    "budgets'). The theme is about what the organisation does or cares about. It is NOT about file "
    "formats, spreadsheets, tables, PDFs or document types. Answer with strict JSON only: "
    '{"name": "2-5 word theme name", "description": "one sentence, max 30 words, what the theme covers", '
    '"synonyms": ["4 to 8 related terms or phrases"]}'
)


@dataclass
class Topic:
    name: str
    description: str
    synonyms: list[str]
    members: list[int]                      # indices into the chunk list
    emb: np.ndarray | None = None           # embedding of "name: description. Synonyms: ..."
    centroid: np.ndarray | None = None      # mean of member chunk embeddings (normalised)
    extra: dict = field(default_factory=dict)

    def text(self) -> str:
        syn = ", ".join(self.synonyms)
        return f"{self.name}: {self.description} Synonyms: {syn}"


def choose_clusters(X: np.ndarray, k_min: int = K_MIN, k_max: int = K_MAX, seed: int = 0):
    """Return (labels, info). KMeans and agglomerative-cosine for each k; best silhouette wins."""
    n = len(X)
    k_max = min(k_max, n - 1)
    best = (-2.0, None, None)
    tried = []
    for k in range(k_min, k_max + 1):
        for algo in ("kmeans", "agglo"):
            if algo == "kmeans":
                lab = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)
            else:
                lab = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(X)
            if len(set(lab)) < 2:
                continue
            s = float(silhouette_score(X, lab, metric="cosine"))
            tried.append((algo, k, round(s, 4)))
            if s > best[0]:
                best = (s, lab, {"algo": algo, "k": k, "silhouette": round(s, 4)})
    return best[1], {**best[2], "tried": tried}


def representatives(X: np.ndarray, chunks: list[Chunk], idx: list[int], n: int = REP_CHUNKS,
                    max_tokens: int = REP_MAX_TOKENS, per_doc: int = 2) -> list[int]:
    cen = X[idx].mean(axis=0)
    cen /= max(np.linalg.norm(cen), 1e-9)
    order = sorted(idx, key=lambda i: -float(X[i] @ cen))
    out, used, per = [], 0, {}
    for i in order:
        d = chunks[i].doc_id
        if per.get(d, 0) >= per_doc:
            continue
        t = min(chunks[i].tokens, 600)
        if out and used + t > max_tokens:
            continue
        out.append(i)
        per[d] = per.get(d, 0) + 1
        used += t
        if len(out) >= n:
            break
    return out


def _clip(text: str, max_tokens: int = 420) -> str:
    return text if count(text) <= max_tokens else text[: max_tokens * 4]


def name_cluster(models: Models, chunks: list[Chunk], rep: list[int]) -> dict:
    parts = []
    for j, i in enumerate(rep, 1):
        c = chunks[i]
        parts.append(doc_block(f"{j} from {clean_title(c.doc_id)}; section: {c.heading_path or '-'}", _clip(c.text)))
    d = models.chat_json(SYSTEM, "\n\n".join(parts))
    name = str(d.get("name", "")).strip() or "Unnamed topic"
    desc = str(d.get("description", "")).strip()
    syn = d.get("synonyms") or []
    if isinstance(syn, str):
        syn = [s.strip() for s in syn.split(",")]
    return {"name": name, "description": desc, "synonyms": [str(s).strip() for s in syn if str(s).strip()][:8]}


def merge_topics(topics: list[Topic], X: np.ndarray, sim: float = MERGE_SIM) -> list[Topic]:
    """Merge topics whose name+description embeddings are more similar than `sim` (keep the larger)."""
    changed = True
    while changed and len(topics) > 1:
        changed = False
        E = np.stack([t.emb for t in topics])
        S = E @ E.T
        np.fill_diagonal(S, -1)
        i, j = np.unravel_index(np.argmax(S), S.shape)
        if S[i, j] > sim:
            a, b = (i, j) if len(topics[i].members) >= len(topics[j].members) else (j, i)
            topics[a].members = sorted(set(topics[a].members + topics[b].members))
            topics.pop(b)
            changed = True
    return topics


def cluster_docs(chunks: list[Chunk], X: np.ndarray, k_range, seed: int = 0):
    """Cluster whole documents (mean chunk embedding) and give every chunk its document's label."""
    docs = sorted({c.doc_id for c in chunks})
    D = np.stack([X[[i for i, c in enumerate(chunks) if c.doc_id == d]].mean(axis=0) for d in docs])
    D /= np.maximum(np.linalg.norm(D, axis=1, keepdims=True), 1e-9)
    dl, info = choose_clusters(D, k_range[0], k_range[1], seed)
    lab = {d: int(l) for d, l in zip(docs, dl)}
    return np.array([lab[c.doc_id] for c in chunks]), info


def discover(models: Models, chunks: list[Chunk], X: np.ndarray, k_range=(K_MIN, K_MAX), seed: int = 0,
             mode: str = "chunk", mu: np.ndarray | None = None):
    """Return (topics, info). X = normalised chunk embeddings aligned with chunks.
    mode 'chunk': cluster chunks. mode 'doc': cluster documents, topic members = all their chunks."""
    if mode == "doc":
        labels, info = cluster_docs(chunks, X, k_range, seed)
    else:
        labels, info = choose_clusters(X, k_range[0], k_range[1], seed)
    info["mode"] = mode
    topics: list[Topic] = []
    for c in sorted(set(labels)):
        idx = [i for i, l in enumerate(labels) if l == c]
        rep = representatives(X, chunks, idx)
        meta = name_cluster(models, chunks, rep)
        topics.append(Topic(meta["name"], meta["description"], meta["synonyms"], idx))
    embs = models.embed([t.text() for t in topics], "passage")
    if mu is not None:  # same centering as the chunk vectors
        embs = embs - mu
        embs = embs / np.maximum(np.linalg.norm(embs, axis=1, keepdims=True), 1e-9)
    for t, e in zip(topics, embs):
        t.emb = e
    n0 = len(topics)
    topics = merge_topics(topics, X)
    info["clusters_before_merge"] = n0
    info["topics_after_merge"] = len(topics)
    for t in topics:
        c = X[t.members].mean(axis=0)
        t.centroid = c / max(np.linalg.norm(c), 1e-9)
    return topics, info


SYSTEM_PROFILE = guard(
    "You analyse a business's document collection. You are given short summaries of documents that "
    "belong together. Name the BUSINESS THEME they share (for example 'Financial reporting and budgets'). "
    "The theme is about what the organisation does or cares about. It is NOT about file formats, "
    "spreadsheets, tables, PDFs or document types. Answer with strict JSON only: "
    '{"name": "2-5 word theme name", "description": "one sentence, max 30 words, what the theme covers", '
    '"synonyms": ["4 to 8 related terms or phrases"]}'
)


def discover_profiles(models: Models, doc_ids: list[str], texts: dict[str, str], P: np.ndarray,
                      chunk_doc: list[str], k_range=(K_MIN, 8), seed: int = 0, mu_p: np.ndarray | None = None):
    """Cluster document-profile vectors P (aligned with doc_ids, centred + normalised). Topic.members are
    chunk indices (all chunks of the member docs); Topic.centroid is the mean of member PROFILE vectors."""
    labels, info = choose_clusters(P, k_range[0], k_range[1], seed)
    info["mode"] = "profile"
    topics: list[Topic] = []
    for c in sorted(set(labels)):
        di = [i for i, l in enumerate(labels) if l == c]
        cen = P[di].mean(axis=0)
        cen /= max(np.linalg.norm(cen), 1e-9)
        order = sorted(di, key=lambda i: -float(P[i] @ cen))[:8]
        user = chr(10).join(doc_block(str(n), texts[doc_ids[i]]) for n, i in enumerate(order, 1))
        d = models.chat_json(SYSTEM_PROFILE, user)
        syn = d.get("synonyms") or []
        if isinstance(syn, str):
            syn = [x.strip() for x in syn.split(",")]
        members_docs = {doc_ids[i] for i in di}
        t = Topic(str(d.get("name", "")).strip() or "Unnamed topic", str(d.get("description", "")).strip(),
                  [str(x).strip() for x in syn if str(x).strip()][:8],
                  [j for j, dd in enumerate(chunk_doc) if dd in members_docs])
        t.centroid = cen
        topics.append(t)
    embs = models.embed([t.text() for t in topics], "passage")
    for t, e in zip(topics, embs):
        t.extra["raw_emb"] = e          # for scoring raw chunk vectors
    if mu_p is not None:
        embs = embs - mu_p
        embs = embs / np.maximum(np.linalg.norm(embs, axis=1, keepdims=True), 1e-9)
    for t, e in zip(topics, embs):
        t.emb = e
    n0 = len(topics)
    while len(topics) > 1:  # merge near-duplicate topics (names+descriptions embed > MERGE_SIM)
        E = np.stack([t.extra["raw_emb"] for t in topics])   # raw (uncentred) text embeddings: 0.9 is meaningful there
        S = E @ E.T
        np.fill_diagonal(S, -1)
        i, j = np.unravel_index(np.argmax(S), S.shape)
        info.setdefault("merge_sims", []).append(round(float(S[i, j]), 3))
        if S[i, j] <= MERGE_SIM:
            break
        a, b = (i, j) if len(topics[i].members) >= len(topics[j].members) else (j, i)
        topics[a].members = sorted(set(topics[a].members + topics[b].members))
        c = topics[a].centroid + topics[b].centroid
        topics[a].centroid = c / max(np.linalg.norm(c), 1e-9)
        topics.pop(b)
    info["clusters_before_merge"] = n0
    info["topics_after_merge"] = len(topics)
    return topics, info
