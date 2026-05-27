"""Keyword rules used to extract synonyms, antonyms, and categories from dict files."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from dictgraph.models import KeywordRule, WordDictEntry

# Purposes used across the converter
PURPOSE_FIELD_WORD = "extract_word"
PURPOSE_FIELD_MEANING = "extract_meaning"
PURPOSE_FIELD_SYNONYMS = "extract_synonyms"
PURPOSE_FIELD_ANTONYMS = "extract_antonyms"
PURPOSE_FIELD_PRIMARY_CATEGORY = "extract_primary_category"
PURPOSE_FIELD_SECONDARY_CATEGORY = "extract_secondary_category"
PURPOSE_FIELD_CATEGORY_TAGS = "extract_category_tags"
PURPOSE_TEXT_WORD_STARTER = "word_section_starter"
PURPOSE_TEXT_MEANING_STARTER = "meaning_section_starter"
PURPOSE_TEXT_SYNONYM_STARTER = "synonym_section_starter"
PURPOSE_TEXT_ANTONYM_STARTER = "antonym_section_starter"
PURPOSE_TEXT_PRIMARY_CATEGORY_STARTER = "primary_category_starter"
PURPOSE_TEXT_SECONDARY_CATEGORY_STARTER = "secondary_category_starter"
PURPOSE_TEXT_CATEGORY_TAGS_STARTER = "category_tags_starter"
PURPOSE_TEXT_DOMAIN_STARTER = "domain_section_starter"
PURPOSE_TEXT_POS_STARTER = "pos_section_starter"
PURPOSE_TEXT_REGISTER_STARTER = "register_section_starter"
PURPOSE_TEXT_RISK_LEVEL_STARTER = "risk_level_section_starter"
PURPOSE_INFER_CATEGORY_RELATION = "infer_category_relation"

_ONTOLOGY_RULE_START_ID = 1000


def default_ontology_phrase_rules() -> list[KeywordRule]:
    """Baseline regex rules for inferring category relations from dict meaning text."""
    rules: list[KeywordRule] = []
    next_id = _ONTOLOGY_RULE_START_ID

    def add(keyword: str, ontology_relation: str) -> None:
        nonlocal next_id
        rules.append(
            KeywordRule(
                id=next_id,
                keyword=keyword,
                purpose_of_keyword=PURPOSE_INFER_CATEGORY_RELATION,
                is_regex=True,
                ontology_relation=ontology_relation,
            )
        )
        next_id += 1

    token = r"([a-z][a-z0-9_\-]{0,32})"
    add(rf"(?i)\b(?:a|an)\s+type\s+of\s+{token}\b", "is_a_type_of")
    add(rf"(?i)\b(?:a|an)\s+kind\s+of\s+{token}\b", "is_a_type_of")
    add(rf"(?i)\bform\s+of\s+{token}\b", "is_a")
    add(rf"(?i)\bpart\s+of\s+{token}\b", "part_of")
    add(rf"(?i)\bgrows?\s+on\s+(?:a|an|the\s+)?{token}\b", "grows_on")
    add(rf"(?i)\bfound\s+in\s+{token}\b", "found_in")
    add(rf"(?i)\brelated\s+to\s+{token}\b", "related_to")
    return rules


def default_text_keyword_rules() -> list[KeywordRule]:
    """Baseline text-label rules for parsing unstructured dict .txt files."""
    rules: list[KeywordRule] = []
    next_id = 1

    def add(keyword: str, purpose: str, is_regex: bool = False) -> None:
        nonlocal next_id
        rules.append(KeywordRule(id=next_id, keyword=keyword, purpose_of_keyword=purpose, is_regex=is_regex))
        next_id += 1

    # Word / headword lines
    add(r"(?i)^word\s*:", PURPOSE_TEXT_WORD_STARTER, is_regex=True)
    add(r"(?i)^word\s*[—\-]\s*", PURPOSE_TEXT_WORD_STARTER, is_regex=True)
    add(r"(?i)^[a-z][a-z\-']+\s*[—\-]\s*(?:adjective|noun|verb|adverb)\b", PURPOSE_TEXT_WORD_STARTER, is_regex=True)
    add(r"(?i)^[a-z][a-z\-']+\s*\((?:adjective|noun|verb|adverb)\)", PURPOSE_TEXT_WORD_STARTER, is_regex=True)
    add(r"(?i)^[a-z][a-z\-']+\s*$", PURPOSE_TEXT_WORD_STARTER, is_regex=True)

    # Meaning / definition
    add(r"(?i)^meaning\s*:", PURPOSE_TEXT_MEANING_STARTER, is_regex=True)
    add(r"(?i)^definition\s*:", PURPOSE_TEXT_MEANING_STARTER, is_regex=True)

    # Synonym / antonym section headers
    add(r"(?i)^synonyms?\s*:", PURPOSE_TEXT_SYNONYM_STARTER, is_regex=True)
    add(r"(?i)^similar\s+(?:words?|terms?)\s*:", PURPOSE_TEXT_SYNONYM_STARTER, is_regex=True)
    add(r"(?i)^words?\s+with\s+similar\s+meaning\s*:", PURPOSE_TEXT_SYNONYM_STARTER, is_regex=True)
    add(r"(?i)^antonyms?\s*:", PURPOSE_TEXT_ANTONYM_STARTER, is_regex=True)
    add(r"(?i)^opposite\s+(?:words?|terms?)\s*:", PURPOSE_TEXT_ANTONYM_STARTER, is_regex=True)
    add(r"(?i)^opposites?\s*:", PURPOSE_TEXT_ANTONYM_STARTER, is_regex=True)

    # Categories and tags
    add(r"(?i)^primary(?:_category)?\s*:", PURPOSE_TEXT_PRIMARY_CATEGORY_STARTER, is_regex=True)
    add(r"(?i)^primary\s*:", PURPOSE_TEXT_PRIMARY_CATEGORY_STARTER, is_regex=True)
    add(r"(?i)^secondary(?:_category)?\s*:", PURPOSE_TEXT_SECONDARY_CATEGORY_STARTER, is_regex=True)
    add(r"(?i)^secondary\s*:", PURPOSE_TEXT_SECONDARY_CATEGORY_STARTER, is_regex=True)
    add(r"(?i)^(?:category\s+)?tags?\s*:", PURPOSE_TEXT_CATEGORY_TAGS_STARTER, is_regex=True)
    add(r"(?i)^category\s+tags?\s*:", PURPOSE_TEXT_CATEGORY_TAGS_STARTER, is_regex=True)
    add(r"(?i)^domain\s*:", PURPOSE_TEXT_DOMAIN_STARTER, is_regex=True)
    add(r"(?i)^category\s*:", PURPOSE_TEXT_DOMAIN_STARTER, is_regex=True)

    # Safety taxonomy fields (new words)
    add(r"(?i)^pos\s*:", PURPOSE_TEXT_POS_STARTER, is_regex=True)
    add(r"(?i)^register\s*:", PURPOSE_TEXT_REGISTER_STARTER, is_regex=True)
    add(r"(?i)^risk_level\s*:", PURPOSE_TEXT_RISK_LEVEL_STARTER, is_regex=True)

    return rules


def default_keyword_rules() -> list[KeywordRule]:
    """Built-in parser + ontology rules (used when keywords_seed.json is missing)."""
    return default_text_keyword_rules() + default_ontology_phrase_rules()


def merge_keyword_rules(base: list[KeywordRule], user: list[KeywordRule]) -> list[KeywordRule]:
    """Merge user rules into base; user rules override base rules with the same id."""
    by_id = {r.id: r for r in base}
    for rule in user:
        by_id[rule.id] = rule
    return sorted(by_id.values(), key=lambda r: r.id)


def load_keyword_rules(seed_path: Path | None) -> list[KeywordRule]:
    """Load user keyword rules from JSON, or built-in defaults if the file is absent."""
    if seed_path and seed_path.is_file():
        return load_keywords_json(seed_path)
    return default_keyword_rules()


def load_keywords_json(path: Path) -> list[KeywordRule]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules: list[KeywordRule] = []
    for item in raw:
        rules.append(
            KeywordRule(
                id=int(item["id"]),
                keyword=item["keyword"],
                purpose_of_keyword=item["purpose_of_keyword"],
                is_regex=bool(item.get("is_regex", False)),
                ontology_relation=str(item.get("ontology_relation", "")).strip(),
            )
        )
    return sorted(rules, key=lambda r: r.id)


def save_keywords_json(path: Path, rules: list[KeywordRule]) -> None:
    payload = [
        {
            "id": r.id,
            "keyword": r.keyword,
            "purpose_of_keyword": r.purpose_of_keyword,
            "is_regex": r.is_regex,
            "ontology_relation": r.ontology_relation,
        }
        for r in rules
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_keywords_csv(path: Path, rules: list[KeywordRule]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "keyword", "purpose_of_keyword", "is_regex", "ontology_relation"],
        )
        writer.writeheader()
        for r in rules:
            writer.writerow(
                {
                    "id": r.id,
                    "keyword": r.keyword,
                    "purpose_of_keyword": r.purpose_of_keyword,
                    "is_regex": str(r.is_regex).lower(),
                    "ontology_relation": r.ontology_relation,
                }
            )


def load_keywords_csv(path: Path) -> list[KeywordRule]:
    rules: list[KeywordRule] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_id = (row.get("id") or "").strip()
            if not row_id or row_id.startswith("#"):
                continue
            rules.append(
                KeywordRule(
                    id=int(row_id),
                    keyword=row["keyword"],
                    purpose_of_keyword=row["purpose_of_keyword"],
                    is_regex=row.get("is_regex", "false").lower() in ("true", "1", "yes"),
                    ontology_relation=row.get("ontology_relation", "").strip(),
                )
            )
    return rules


def apply_field_keywords(data: dict[str, Any], rules: list[KeywordRule]) -> WordDictEntry:
    """Extract structured fields using keyword rules mapped to JSON keys."""
    field_map = {
        PURPOSE_FIELD_WORD: "word",
        PURPOSE_FIELD_MEANING: "meaning",
        PURPOSE_FIELD_SYNONYMS: "synonyms",
        PURPOSE_FIELD_ANTONYMS: "antonyms",
        PURPOSE_FIELD_PRIMARY_CATEGORY: "primary_category",
        PURPOSE_FIELD_SECONDARY_CATEGORY: "secondary_category",
        PURPOSE_FIELD_CATEGORY_TAGS: "category_tags",
    }
    extracted: dict[str, Any] = {}
    for rule in rules:
        if rule.is_regex or rule.purpose_of_keyword not in field_map:
            continue
        key = field_map[rule.purpose_of_keyword]
        if rule.keyword in data and key not in extracted:
            extracted[key] = data[rule.keyword]
    return WordDictEntry.from_dict(extracted if extracted else data)


def match_keyword(keyword: str, text: str, is_regex: bool) -> bool:
    if is_regex:
        return bool(re.search(keyword, text, re.IGNORECASE))
    return keyword.lower() == text.lower()
