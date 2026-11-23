"""Document profiles: one short LLM summary per document, in business terms.

Why: mean chunk embeddings group documents by FORMAT (spreadsheet tables look alike), not by business
theme. A two-sentence summary that ignores format embeds by meaning. Cached on disk by (model, sha1(input)).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .chunk import Chunk, clean_title
from .llm import Models, doc_block, guard

PROMPT_VERSION = "profile-v3"
HEAD_TOKENS_CHARS = 5000   # about 1,200 tokens of the document go to the LLM (profile input only; stored MD is never cut)

SYSTEM = guard(
    "You read the start of one business document and say what BUSINESS AREA it belongs to. "
    "Ignore the file format: do not mention spreadsheet, table, columns, rows, PDF or slides. "
    "Say what the organisation does or cares about in this document (for example: money and budgets, "
    "staff and pay, flooding, data and technology, wildlife and waste). "
    'Answer with strict JSON only: {"summary": "two sentences, max 45 words", "area": "2 to 4 words"}'
)


N_SAMPLES = 1   # tried 3 summaries per doc with averaged embeddings: no gain (0.73-0.79 lenient), 2-3x slower


def build_profiles(models: Models, chunks: list[Chunk], n_samples: int = N_SAMPLES, on_progress=None) -> dict[str, dict]:
    """Return {doc_id: {"summary": str, "area": str, "samples": [{"summary","area"}, ...]}}."""
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.doc_id, []).append(c)
    jobs = {}
    for d, cs in by_doc.items():
        # spread the excerpt over the document: first chunk, then evenly spaced others
        picks = [cs[i] for i in sorted({0, len(cs) // 3, 2 * len(cs) // 3})]
        body = "\n\n".join((c.heading_path + "\n" if c.heading_path else "") + c.text[:HEAD_TOKENS_CHARS // len(picks)] for c in picks)
        jobs[d] = "Describe this document.\n" + doc_block(clean_title(d), body)  # name = label of the delimited block
    res: dict[str, dict] = {d: {"samples": []} for d in jobs}

    def run(item):
        (d, user), si = item
        try:  # temperature 0 + fixed seed; cached by (model, PROMPT_VERSION, sha of prompt)
            r = models.cached_json(PROMPT_VERSION if si == 0 else f"{PROMPT_VERSION}-s{si}", SYSTEM, user, max_tokens=300)
            out = {"summary": str(r.get("summary", "")).strip(), "area": str(r.get("area", "")).strip()}
        except Exception:
            out = {"summary": "", "area": ""}
        return d, si, out

    work = [(it, si) for si in range(n_samples) for it in jobs.items()]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n_done, (d, si, out) in enumerate(ex.map(run, work), 1):
            if on_progress:
                on_progress("profile", n_done, len(work))
            if out["summary"]:
                res[d]["samples"].append(out)
    for d, r in res.items():
        first = r["samples"][0] if r["samples"] else {"summary": "", "area": ""}
        r.update(first)
    return res


def profile_text(doc_id: str, p: dict) -> str:
    return f"{clean_title(doc_id)}. {p.get('area', '')}. {p.get('summary', '')}".strip()


def profile_texts(doc_id: str, p: dict) -> list[str]:
    """One text per sample (or the single fallback text)."""
    return [profile_text(doc_id, x) for x in p.get("samples") or [p]]
