"""Doc -> topic links: score from chunk similarity (+ optional rerank), confidence, threshold."""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from .chunk import Chunk
from .llm import Models
from .topics import Topic

TOP_N = 3
BLEND = 0.5          # weight of topic-text embedding vs member centroid
TAU = 0.03           # softmax temperature for confidence
THRESHOLD = 0.20     # minimum confidence to keep a (non-best) link
RERANK_W = 0.10      # rerank adjusts the score by up to +-RERANK_W/2


@dataclass
class DocLink:
    doc_id: str
    topic: int                    # index into topics list
    score: float
    confidence: float
    evidence: list[dict] = field(default_factory=list)   # {chunk, heading, snippet, sim}
    role: str = "primary"        # primary | secondary | alternative
    disagreement: bool = False    # LLM and embedding disagree -> review-queue priority


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(x, 30), -30)))


def link_docs(models: Models, chunks: list[Chunk], X: np.ndarray, topics: list[Topic],
              rerank: bool | None = None, blend: float = BLEND, tau: float = TAU,
              threshold: float = THRESHOLD, top_n: int = TOP_N) -> list[DocLink]:
    use_rerank = models.rerank_enabled if rerank is None else (rerank and models.rerank_enabled)
    T = np.stack([t.emb for t in topics])            # (k, d)
    C = np.stack([t.centroid for t in topics])
    by_doc: dict[str, list[int]] = {}
    for i, c in enumerate(chunks):
        by_doc.setdefault(c.doc_id, []).append(i)

    def sims_for(idx: list[int]):
        A = X[idx] @ T.T                              # (n, k)
        B = X[idx] @ C.T
        return blend * A + (1 - blend) * B

    # rerank jobs: (doc, topic) -> adjustment
    adj: dict[tuple[str, int], float] = {}
    if use_rerank:
        jobs = []
        for d, idx in by_doc.items():
            S = sims_for(idx)
            for k in range(len(topics)):
                top = np.argsort(-S[:, k])[:top_n]
                jobs.append((d, k, [chunks[idx[j]].text for j in top]))

        def run(job):
            d, k, passages = job
            logits = models.rerank(topics[k].text(), passages)
            return (d, k), float(np.mean(logits))

        with ThreadPoolExecutor(max_workers=6) as ex:
            for key, lg in ex.map(run, jobs):
                adj[key] = _sigmoid(lg)

    out: list[DocLink] = []
    for d, idx in by_doc.items():
        S = sims_for(idx)
        scores = []
        for k in range(len(topics)):
            top = np.argsort(-S[:, k])[:top_n]
            s = float(np.mean(S[top, k]))
            if use_rerank:
                s += RERANK_W * (adj[(d, k)] - 0.5)
            scores.append(s)
        z = np.array(scores) / tau
        p = np.exp(z - z.max())
        p /= p.sum()
        order = np.argsort(-p)
        for rank, k in enumerate(order):
            if rank > 0 and p[k] < threshold:
                break
            top = np.argsort(-S[:, k])[:top_n]
            ev = [{"chunk": int(idx[j]), "heading": chunks[idx[j]].heading_path,
                   "snippet": chunks[idx[j]].text[:240].replace("\n", " "), "sim": round(float(S[j, k]), 4)}
                  for j in top]
            out.append(DocLink(d, int(k), round(scores[k], 4), round(float(p[k]), 4), ev))
    return out


PROFILE_W = 0.7      # weight of the document-profile similarity vs the chunk similarity
PROFILE_TAU = 0.05


def link_docs_profile(chunks: list[Chunk], Xraw: np.ndarray, doc_ids: list[str], P: np.ndarray,
                      topics: list[Topic], w: float = PROFILE_W, tau: float = PROFILE_TAU,
                      threshold: float = THRESHOLD, top_n: int = TOP_N, blend: float = BLEND,
                      summaries: dict[str, str] | None = None) -> list[DocLink]:
    """Score = w * profile similarity (topic text + member-profile centroid, centred space)
    + (1-w) * mean of the top-n raw chunk similarities to the topic text."""
    T = np.stack([t.emb for t in topics])
    C = np.stack([t.centroid for t in topics])
    R = np.stack([t.extra["raw_emb"] for t in topics])
    by_doc: dict[str, list[int]] = {}
    for i, c in enumerate(chunks):
        by_doc.setdefault(c.doc_id, []).append(i)
    out: list[DocLink] = []
    for di, d in enumerate(doc_ids):
        idx = by_doc[d]
        S = Xraw[idx] @ R.T                                   # (n_chunks, k)
        prof = blend * (P[di] @ T.T) + (1 - blend) * (P[di] @ C.T)
        scores = []
        for k in range(len(topics)):
            top = np.argsort(-S[:, k])[:top_n]
            scores.append(w * float(prof[k]) + (1 - w) * float(np.mean(S[top, k])))
        z = np.array(scores) / tau
        p = np.exp(z - z.max())
        p /= p.sum()
        for rank, k in enumerate(np.argsort(-p)):
            if rank > 0 and p[k] < threshold:
                break
            top = np.argsort(-S[:, k])[:top_n]
            ev = []
            if summaries and summaries.get(d):
                ev.append({"chunk": None, "heading": "(document profile)", "snippet": summaries[d][:240],
                           "sim": round(float(prof[k]), 4)})
            ev += [{"chunk": int(idx[j]), "heading": chunks[idx[j]].heading_path,
                    "snippet": chunks[idx[j]].text[:240].replace(chr(10), " "), "sim": round(float(S[j, k]), 4)}
                   for j in top]
            out.append(DocLink(d, int(k), round(scores[k], 4), round(float(p[k]), 4), ev))
    return out
