"""The official SSM definitions of the taxonomy concepts, for the agents'
`lookup_definitions` tool.

The data is copied unchanged from v1 (`concept_model/concept_definitions_mfrs.json`
and `_mpers.json`, commit 4bb9c6bf): a list of `{concept_id, label,
label_normalized, definition}` per standard. The ranking is v1's
(`concept_model/definitions.py`): exact label, then one label inside the
other, then word overlap and a fuzzy ratio, with a small lift when the
query's words appear in the definition. Read only; loaded once per standard.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

FOLDER = Path(__file__).with_name("definitions")
STANDARDS = ("mfrs", "mpers")
MATCH_THRESHOLD = 0.40


def normalize(label: str) -> str:
    """v1's label key: no leading *, lower case, no trailing [text block]-style suffix."""
    text = (label or "").strip().lstrip("*").strip().lower()
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", text).strip()


@lru_cache(maxsize=None)
def load(standard: str) -> tuple[dict, ...]:
    standard = (standard or "").lower()
    if standard not in STANDARDS:
        raise ValueError(f"There are no definitions for the standard {standard!r}.")
    entries = json.loads((FOLDER / f"concept_definitions_{standard}.json").read_text(encoding="utf-8"))
    return tuple(entries)


@lru_cache(maxsize=None)
def _by_id(standard: str) -> dict[str, dict]:
    return {e["concept_id"]: e for e in load(standard)}


def definition_of(standard: str, concept_id: str) -> str:
    """The official definition of one SSM element, or '' when none is recorded."""
    entry = _by_id((standard or "").lower()).get(concept_id or "")
    return " ".join((entry or {}).get("definition", "").split())


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", normalize(text)) if t}


def _score(query: str, tokens: set[str], entry: dict) -> float:
    label = entry.get("label_normalized") or normalize(entry.get("label", ""))
    if not label:
        return 0.0
    if query == label:
        return 1.0
    if query in label or label in query:
        return 0.80 + 0.15 * (min(len(query), len(label)) / max(len(query), len(label)))
    overlap = len(tokens & _tokens(label)) / len(tokens) if tokens else 0.0
    score = max(overlap * 0.75, SequenceMatcher(None, query, label).ratio() * 0.65)
    definition = (entry.get("definition") or "").lower()
    if tokens:
        score += 0.20 * sum(1 for t in tokens if t in definition) / len(tokens)
    return min(1.0, score)


def search(standard: str, query: str, top: int = 4) -> list[dict]:
    """The best-matching definitions for words a person or agent would use."""
    norm, tokens = normalize(query), _tokens(query)
    if not norm:
        return []
    scored = [(s, e) for e in load(standard) if (s := _score(norm, tokens, e)) >= MATCH_THRESHOLD]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [e for _, e in scored[:top]]
