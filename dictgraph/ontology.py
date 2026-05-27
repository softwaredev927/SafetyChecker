"""Infer directed category relations from dict text using keyword regex rules."""

from __future__ import annotations

import re
from typing import Iterable

from dictgraph.keywords import PURPOSE_INFER_CATEGORY_RELATION
from dictgraph.models import CategoryNode, KeywordRule, WordDictEntry

# Default scores for phrase-inferred relations
ONTOLOGY_RELATION_SCORES: dict[str, float] = {
    "is_a": 0.85,
    "is_a_type_of": 0.78,
    "part_of": 0.72,
    "grows_on": 0.50,
    "found_in": 0.50,
    "related_to": 0.55,
}
DEFAULT_INFERRED_SCORE = 0.55


def resolve_category_token(token: str, categories: list[CategoryNode]) -> str | None:
    """Map a captured token to a known category name."""
    normalized = token.strip().lower().replace(" ", "_")
    if not normalized:
        return None

    names = {c.category_name for c in categories}
    if normalized in names:
        return normalized

    # Simple plural strip: trees -> tree (if tree is a category)
    if normalized.endswith("s") and len(normalized) > 2:
        singular = normalized[:-1]
        if singular in names:
            return singular

    return None


def _infer_rules(rules: list[KeywordRule]) -> list[KeywordRule]:
    return [
        r
        for r in rules
        if r.purpose_of_keyword == PURPOSE_INFER_CATEGORY_RELATION and r.ontology_relation
    ]


def _entry_source_category(entry: WordDictEntry) -> str:
    if entry.secondary_category:
        return entry.secondary_category
    return entry.primary_category


def _entry_text_for_inference(entry: WordDictEntry) -> str:
    parts: list[str] = []
    if entry.meaning:
        parts.append(entry.meaning)
    if entry.category_tags:
        parts.append(" ".join(entry.category_tags))
    return " ".join(parts)


def infer_relations_from_entries(
    entries: list[WordDictEntry],
    categories: list[CategoryNode],
    rules: list[KeywordRule],
) -> list[tuple[str, str, str, float]]:
    """
    Scan dict entry text for ontology phrase patterns.
    Returns (source_category, target_category, ontology_relation, score) tuples.
    """
    c2id = {c.category_name: c.id for c in categories}
    infer_rules = _infer_rules(rules)
    if not infer_rules:
        return []

    edge_map: dict[tuple[str, str, str], float] = {}

    def add_edge(source: str, target: str, relation: str, score: float) -> None:
        if not source or not target or source == target:
            return
        if source not in c2id or target not in c2id:
            return
        key = (source, target, relation)
        rounded = max(-1.0, min(1.0, round(score, 4)))
        if key not in edge_map or abs(rounded) > abs(edge_map[key]):
            edge_map[key] = rounded

    for entry in entries:
        source_name = _entry_source_category(entry)
        if not source_name:
            continue
        text = _entry_text_for_inference(entry)
        if not text:
            continue

        for rule in infer_rules:
            relation = rule.ontology_relation
            score = ONTOLOGY_RELATION_SCORES.get(relation, DEFAULT_INFERRED_SCORE)
            try:
                for match in re.finditer(rule.keyword, text, re.IGNORECASE):
                    if match.lastindex is None or match.lastindex < 1:
                        continue
                    captured = match.group(1)
                    target_name = resolve_category_token(captured, categories)
                    if target_name:
                        add_edge(source_name, target_name, relation, score)
            except re.error:
                continue

    return [(s, t, r, sc) for (s, t, r), sc in sorted(edge_map.items())]


def merge_directed_edges(
    edges: Iterable[tuple[int, int, str, float]],
) -> dict[tuple[int, int, str], float]:
    """Merge directed edges keyed by (source_id, target_id, ontology_relation)."""
    edge_map: dict[tuple[int, int, str], float] = {}
    for source_id, target_id, relation, score in edges:
        if source_id == target_id:
            continue
        key = (source_id, target_id, relation)
        rounded = max(-1.0, min(1.0, round(score, 4)))
        if key not in edge_map or abs(rounded) > abs(edge_map[key]):
            edge_map[key] = rounded
    return edge_map


def symmetric_edge_ids(a_id: int, b_id: int) -> tuple[int, int]:
    """For symmetric relations, source = lower id."""
    return (min(a_id, b_id), max(a_id, b_id))
