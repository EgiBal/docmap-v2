"""Folder locations. Defaults are the repo layout; each can be set by an env var (the CLIs set them from flags).

DOCMAP_MD_DIR, DOCMAP_CACHE_DIR, DOCMAP_SCRATCH_DIR, DOCMAP_CORPUS_DIR, DOCMAP_NOTES_DIR.
Read at call time, so a CLI flag or a test can change them after import."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # the repo folder (backend/docmap/paths.py -> repo)


def _p(var: str, default: Path) -> Path:
    return Path(os.environ.get(var) or default)


def md_dir() -> Path:
    return _p("DOCMAP_MD_DIR", ROOT / "data" / "md")


def cache_dir() -> Path:
    return _p("DOCMAP_CACHE_DIR", ROOT / "data" / "cache")


def scratch_dir() -> Path:
    return _p("DOCMAP_SCRATCH_DIR", ROOT / "data" / "scratch")


def corpus_dir() -> Path:
    return _p("DOCMAP_CORPUS_DIR", ROOT / "corpus" / "raw")


def notes_dir() -> Path:
    return _p("DOCMAP_NOTES_DIR", ROOT / "notes")


def set_env(**kw) -> None:
    """Set DOCMAP_* env vars from CLI flags (None values are ignored). Keys: md_dir, cache_dir, scratch_dir, corpus_dir, notes_dir."""
    for k, v in kw.items():
        if v:
            os.environ["DOCMAP_" + k.upper()] = str(Path(v).resolve())
