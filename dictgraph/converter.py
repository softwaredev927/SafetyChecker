"""
Convert file-based dictionary data into CSV ontology graphs.

Outputs:
  - categories.csv          (category graph nodes)
  - words.csv               (word graph nodes)
  - edges.csv               (word graph edges, relation_score in [-1, 1])
  - category_relations.csv  (category graph edges)
  - keywords.csv            (extraction / matching rules)
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Callable
from typing import Iterable

from dictgraph.keywords import (
    PURPOSE_TEXT_ANTONYM_STARTER,
    PURPOSE_TEXT_CATEGORY_TAGS_STARTER,
    PURPOSE_TEXT_DOMAIN_STARTER,
    PURPOSE_TEXT_MEANING_STARTER,
    PURPOSE_TEXT_POS_STARTER,
    PURPOSE_TEXT_PRIMARY_CATEGORY_STARTER,
    PURPOSE_TEXT_REGISTER_STARTER,
    PURPOSE_TEXT_RISK_LEVEL_STARTER,
    PURPOSE_TEXT_SECONDARY_CATEGORY_STARTER,
    PURPOSE_TEXT_SYNONYM_STARTER,
    PURPOSE_TEXT_WORD_STARTER,
    default_keyword_rules,
    load_keyword_rules,
    match_keyword,
    save_keywords_csv,
)
from dictgraph.ontology import (
    infer_relations_from_entries,
    merge_directed_edges,
    symmetric_edge_ids,
)
from dictgraph.models import (
    CategoryEdge,
    CategoryNode,
    KeywordRule,
    WordCategoryAssignment,
    WordDictEntry,
    WordEdge,
    WordNode,
    WordPairLevel,
)

SYNONYM_SCORE = 0.92
ANTONYM_SCORE = -0.92
PARTIAL_SYNONYM_SCORE = 0.75
PARTIAL_ANTONYM_SCORE = -0.75
PARENT_CHILD_CATEGORY_SCORE = 0.85
SIBLING_CATEGORY_SCORE = 0.55
OPPOSING_SECONDARY_CATEGORY_SCORE = -0.70

ROOT_CATEGORY = "attribute"
SAFETY_ROOT = "lexicon"
VALID_POS = frozenset({"noun", "verb", "adjective", "adverb"})


def _rules_for_purpose(rules: list[KeywordRule], purpose: str) -> list[KeywordRule]:
    return [r for r in rules if r.purpose_of_keyword == purpose]


def _line_matches_purpose(line: str, rules: list[KeywordRule], purpose: str) -> bool:
    return any(match_keyword(r.keyword, line, r.is_regex) for r in _rules_for_purpose(rules, purpose))


def _split_word_tokens(text: str) -> list[str]:
    return [t.strip().lower() for t in re.split(r"[,;]", text) if t.strip()]


def _split_category_pair(text: str) -> tuple[str, str]:
    parts = re.split(r"\s*[|—\-]\s*", text.strip(), maxsplit=1)
    primary = parts[0].strip().lower()
    secondary = parts[1].strip().lower() if len(parts) > 1 else ""
    return primary, secondary


def _extract_word_from_line(line: str) -> tuple[str, str]:
    stripped = line.strip()
    pos = ""

    m = re.match(r"(?i)^word\s*:\s*(.+)$", stripped)
    if m:
        rest = m.group(1).strip()
        m2 = re.match(r"(?i)^([a-z][a-z\-']+)\s*[—\-]\s*(adjective|noun|verb|adverb)\b", rest)
        if m2:
            return m2.group(1).strip().lower(), m2.group(2).strip().lower()
        return rest.split()[0].strip().lower() if rest else "", pos

    m = re.match(r"(?i)^word\s*[—\-]\s*(.+)$", stripped)
    if m:
        return m.group(1).strip().lower(), pos

    m = re.match(r"(?i)^([a-z][a-z\-']+)\s*[—\-]\s*(adjective|noun|verb|adverb)\b", stripped)
    if m:
        return m.group(1).strip().lower(), m.group(2).strip().lower()

    m = re.match(r"(?i)^([a-z][a-z\-']+)\s*\((adjective|noun|verb|adverb)\)", stripped)
    if m:
        return m.group(1).strip().lower(), m.group(2).strip().lower()

    m = re.match(r"(?i)^([a-z][a-z\-']+)\s*$", stripped)
    if m:
        return m.group(1).strip().lower(), pos

    return "", pos


def _parse_risk_level(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    return max(0.0, min(1.0, round(float(text), 4)))


def _is_legacy_domain_value(value: str) -> bool:
    """Legacy Domain lines use 'emotion | positive' pairs, not single safety domains."""
    if "|" in value:
        return True
    parts = re.split(r"\s*[—\-]\s*", value.strip(), maxsplit=1)
    return len(parts) == 2 and bool(parts[0].strip()) and bool(parts[1].strip())


def _value_after_colon(line: str) -> str:
    if ":" in line:
        return line.split(":", 1)[1].strip()
    return ""


def parse_text_dict_file(
    content: str,
    rules: list[KeywordRule],
    *,
    source_file: str = "",
    fallback_word: str = "",
) -> WordDictEntry:
    """Parse unstructured line-oriented dict .txt files using keyword rules."""
    data: dict[str, list[str] | str] = {
        "synonyms": [],
        "antonyms": [],
        "category_tags": [],
    }
    section: str | None = None
    expecting_meaning = False

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            section = None
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_WORD_STARTER):
            word, pos = _extract_word_from_line(line)
            is_standalone = bool(re.fullmatch(r"[a-z][a-z\-']+", line, re.IGNORECASE))
            if word and (not is_standalone or not data.get("word")):
                data["word"] = word
                if pos and not data.get("pos"):
                    data["pos"] = pos
                expecting_meaning = not data.get("meaning")
                section = None
                continue
            if not (is_standalone and section):
                continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_MEANING_STARTER):
            value = _value_after_colon(line)
            if value:
                data["meaning"] = value
            expecting_meaning = False
            section = None
            continue

        if expecting_meaning and not any(
            _line_matches_purpose(line, rules, p)
            for p in (
                PURPOSE_TEXT_SYNONYM_STARTER,
                PURPOSE_TEXT_ANTONYM_STARTER,
                PURPOSE_TEXT_PRIMARY_CATEGORY_STARTER,
                PURPOSE_TEXT_SECONDARY_CATEGORY_STARTER,
                PURPOSE_TEXT_CATEGORY_TAGS_STARTER,
                PURPOSE_TEXT_DOMAIN_STARTER,
                PURPOSE_TEXT_POS_STARTER,
                PURPOSE_TEXT_REGISTER_STARTER,
                PURPOSE_TEXT_RISK_LEVEL_STARTER,
            )
        ):
            data["meaning"] = line
            expecting_meaning = False
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_SYNONYM_STARTER):
            section = "synonyms"
            rest = _value_after_colon(line)
            if rest:
                data["synonyms"].extend(_split_word_tokens(rest))  # type: ignore[union-attr]
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_ANTONYM_STARTER):
            section = "antonyms"
            rest = _value_after_colon(line)
            if rest:
                data["antonyms"].extend(_split_word_tokens(rest))  # type: ignore[union-attr]
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_PRIMARY_CATEGORY_STARTER):
            value = _value_after_colon(line).lower()
            if value:
                data["primary_category"] = value
            section = None
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_SECONDARY_CATEGORY_STARTER):
            value = _value_after_colon(line).lower()
            if value:
                data["secondary_category"] = value
            section = None
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_DOMAIN_STARTER):
            value = _value_after_colon(line)
            if _is_legacy_domain_value(value):
                primary, secondary = _split_category_pair(value)
                if primary:
                    data["primary_category"] = primary
                if secondary:
                    data["secondary_category"] = secondary
            elif value:
                data["domain"] = value.strip().lower()
            section = None
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_POS_STARTER):
            value = _value_after_colon(line).lower()
            if value in VALID_POS:
                data["pos"] = value
            section = None
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_REGISTER_STARTER):
            value = _value_after_colon(line).lower()
            if value:
                data["register"] = value
            section = None
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_RISK_LEVEL_STARTER):
            value = _value_after_colon(line)
            if value:
                data["risk_level"] = _parse_risk_level(value)
            section = None
            continue

        if _line_matches_purpose(line, rules, PURPOSE_TEXT_CATEGORY_TAGS_STARTER):
            section = "category_tags"
            rest = _value_after_colon(line)
            if rest:
                data["category_tags"].extend(_split_word_tokens(rest))  # type: ignore[union-attr]
            continue

        if section in ("synonyms", "antonyms", "category_tags"):
            if section == "category_tags":
                data["category_tags"].extend(_split_word_tokens(line))  # type: ignore[union-attr]
            else:
                tokens = _split_word_tokens(line) if "," in line else [line.lower()]
                data[section].extend(tokens)  # type: ignore[union-attr]
            continue

    if not data.get("word") and fallback_word:
        data["word"] = fallback_word.lower()

    entry = WordDictEntry.from_dict(data)  # type: ignore[arg-type]
    entry.source_file = source_file
    return entry


def load_dict_files(
    dict_data_dir: Path,
    *,
    rules: list[KeywordRule] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[WordDictEntry]:
    parse_rules = rules or default_keyword_rules()
    paths = sorted(dict_data_dir.glob("*.txt"))
    if not paths:
        raise ValueError(f"No .txt dict files found in {dict_data_dir}")

    entries: list[WordDictEntry] = []
    for index, path in enumerate(paths, start=1):
        content = path.read_text(encoding="utf-8")
        entries.append(
            parse_text_dict_file(
                content,
                parse_rules,
                source_file=path.name,
                fallback_word=path.stem,
            )
        )
        if progress_callback:
            progress_callback(index, len(paths))
    return entries


def extract_categories(entries: list[WordDictEntry]) -> list[CategoryNode]:
    """Build category nodes for legacy (attribute) and safety (lexicon) trees."""
    names: dict[str, str] = {ROOT_CATEGORY: "", SAFETY_ROOT: ""}

    for entry in entries:
        if entry.is_safety_taxonomy():
            if entry.pos:
                names.setdefault(entry.pos, SAFETY_ROOT)
            if entry.register:
                parent = entry.pos or SAFETY_ROOT
                names.setdefault(entry.register, parent)
            if entry.domain:
                parent = entry.register or entry.pos or SAFETY_ROOT
                names.setdefault(entry.domain, parent)
            tag_parent = entry.domain or entry.register or entry.pos or SAFETY_ROOT
            for tag in entry.category_tags:
                if tag not in names:
                    names[tag] = tag_parent
        else:
            if entry.primary_category:
                names.setdefault(entry.primary_category, ROOT_CATEGORY)
            if entry.secondary_category and entry.primary_category:
                names.setdefault(entry.secondary_category, entry.primary_category)
            for tag in entry.category_tags:
                parent = entry.primary_category or ROOT_CATEGORY
                if tag not in names:
                    names[tag] = parent

    ordered = [ROOT_CATEGORY, SAFETY_ROOT] + sorted(
        n for n in names if n not in (ROOT_CATEGORY, SAFETY_ROOT)
    )

    def _depth(name: str, memo: dict[str, int]) -> int:
        if name in memo:
            return memo[name]
        parent = names.get(name, "")
        if not parent:
            memo[name] = 0
        else:
            memo[name] = _depth(parent, memo) + 1
        return memo[name]

    depth_map: dict[str, int] = {}
    for name in ordered:
        _depth(name, depth_map)

    return [
        CategoryNode(
            id=i + 1,
            parent_category=names[name],
            category_name=name,
            category_level=depth_map[name],
        )
        for i, name in enumerate(ordered)
    ]


def apply_category_risk_levels(
    categories: list[CategoryNode],
    words: list[WordNode],
    overrides: dict[str, float],
) -> None:
    """Set default_risk_level on categories from word maxima and optional overrides."""
    word_risks_by_category: dict[str, list[float]] = {}
    for w in words:
        if w.risk_level is None:
            continue
        for cat in (w.pos, w.register, w.domain, w.primary_category, w.secondary_category):
            if cat:
                word_risks_by_category.setdefault(cat, []).append(w.risk_level)
        for tag in w.category_tags:
            word_risks_by_category.setdefault(tag, []).append(w.risk_level)

    for cat in categories:
        computed: float | None = None
        if cat.category_name in word_risks_by_category:
            computed = max(word_risks_by_category[cat.category_name])
        if cat.category_name in overrides:
            cat.default_risk_level = overrides[cat.category_name]
        elif computed is not None:
            cat.default_risk_level = round(computed, 4)


def load_category_risk_overrides(dict_data_dir: Path) -> dict[str, float]:
    path = dict_data_dir / "category_risk_overrides.csv"
    if not path.is_file():
        return {}
    overrides: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("category_name") or "").strip().lower()
            level_raw = (row.get("default_risk_level") or "").strip()
            if name and level_raw:
                overrides[name] = max(0.0, min(1.0, round(float(level_raw), 4)))
    return overrides


def load_word_risk_overrides(dict_data_dir: Path) -> dict[str, float]:
    path = dict_data_dir / "word_risk_overrides.csv"
    if not path.is_file():
        return {}
    overrides: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            token = (row.get("word") or "").strip().lower()
            level_raw = (row.get("risk_level") or "").strip()
            if token and level_raw:
                overrides[token] = max(0.0, min(1.0, round(float(level_raw), 4)))
    return overrides


def apply_word_risk_overrides(words: list[WordNode], overrides: dict[str, float]) -> None:
    for w in words:
        if w.word in overrides:
            w.risk_level = overrides[w.word]


def build_word_nodes(entries: list[WordDictEntry]) -> list[WordNode]:
    return [
        WordNode(
            id=i + 1,
            word=e.word,
            meaning=e.meaning,
            primary_category=e.primary_category,
            secondary_category=e.secondary_category,
            pos=e.pos,
            register=e.register,
            domain=e.domain,
            risk_level=e.risk_level,
            category_tags=list(e.category_tags),
        )
        for i, e in enumerate(entries)
    ]


def build_word_category_assignments(words: list[WordNode]) -> list[WordCategoryAssignment]:
    assignments: list[WordCategoryAssignment] = []
    for w in words:
        if w.pos:
            assignments.append(WordCategoryAssignment(w.id, w.pos, "pos"))
        if w.register:
            assignments.append(WordCategoryAssignment(w.id, w.register, "register"))
        if w.domain:
            assignments.append(WordCategoryAssignment(w.id, w.domain, "domain"))
        if w.primary_category:
            assignments.append(WordCategoryAssignment(w.id, w.primary_category, "legacy_primary"))
        if w.secondary_category:
            assignments.append(WordCategoryAssignment(w.id, w.secondary_category, "legacy_secondary"))
        for tag in w.category_tags:
            assignments.append(WordCategoryAssignment(w.id, tag, "tag"))
    return assignments


def load_word_pair_seeds(dict_data_dir: Path) -> list[WordPairLevel]:
    path = dict_data_dir / "word_pairs_seed.csv"
    if not path.is_file():
        return []
    pairs: list[WordPairLevel] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a = (row.get("word_a") or "").strip().lower()
            b = (row.get("word_b") or "").strip().lower()
            level_raw = (row.get("risk_level") or "").strip()
            if a and b and level_raw:
                pairs.append(
                    WordPairLevel(
                        word_a=min(a, b),
                        word_b=max(a, b),
                        risk_level=max(0.0, min(1.0, round(float(level_raw), 4))),
                        source="explicit",
                    )
                )
    return pairs


def build_word_pair_levels(
    words: list[WordNode],
    word_edges: list[WordEdge],
    explicit_pairs: list[WordPairLevel],
) -> list[WordPairLevel]:
    w2word = {w.id: w.word for w in words}
    wrisk = {w.word: w.risk_level for w in words if w.risk_level is not None}

    pair_map: dict[tuple[str, str], WordPairLevel] = {}
    for p in explicit_pairs:
        key = (p.word_a, p.word_b)
        pair_map[key] = p

    for edge in word_edges:
        if edge.relation_score <= 0:
            continue
        wa = w2word.get(edge.word_id_a, "")
        wb = w2word.get(edge.word_id_b, "")
        if not wa or not wb:
            continue
        ra, rb = wrisk.get(wa), wrisk.get(wb)
        if ra is None or rb is None:
            continue
        key = (min(wa, wb), max(wa, wb))
        derived_level = max(ra, rb)
        existing = pair_map.get(key)
        if existing is None or existing.source == "derived":
            pair_map[key] = WordPairLevel(
                word_a=key[0],
                word_b=key[1],
                risk_level=round(derived_level, 4),
                source="derived",
            )
        elif existing.source == "explicit":
            pass

    return sorted(pair_map.values(), key=lambda p: (p.word_a, p.word_b))


def category_name_to_id(categories: list[CategoryNode]) -> dict[str, int]:
    return {c.category_name: c.id for c in categories}


def word_to_id(words: list[WordNode]) -> dict[str, int]:
    return {w.word: w.id for w in words}


def _normalize_list(values: Iterable[str]) -> list[str]:
    return [v.strip().lower() for v in values if v and str(v).strip()]


def extract_word_relations(
    entries: list[WordDictEntry],
    words: list[WordNode],
    _rules: list[KeywordRule],
) -> list[WordEdge]:
    """
    Find synonym/antonym edges between word nodes using dict content.
    Keyword rules (see keywords.csv) define how fields are discovered in source files.
    Only edges where both endpoints exist in the word table are emitted.
    """
    w2id = word_to_id(words)
    known = set(w2id.keys())
    edge_map: dict[tuple[int, int], float] = {}

    def add_edge(a: int, b: int, score: float) -> None:
        if a == b:
            return
        key = (min(a, b), max(a, b))
        if key not in edge_map or abs(score) > abs(edge_map[key]):
            edge_map[key] = max(-1.0, min(1.0, round(score, 4)))

    for entry in entries:
        src_id = w2id.get(entry.word)
        if src_id is None:
            continue

        synonyms = _normalize_list(entry.synonyms)
        antonyms = _normalize_list(entry.antonyms)

        for syn in synonyms:
            tgt = w2id.get(syn)
            if tgt is not None:
                score = SYNONYM_SCORE if syn in known else PARTIAL_SYNONYM_SCORE
                add_edge(src_id, tgt, score)

        for ant in antonyms:
            tgt = w2id.get(ant)
            if tgt is not None:
                score = ANTONYM_SCORE if ant in known else PARTIAL_ANTONYM_SCORE
                add_edge(src_id, tgt, score)

        # Mutual reinforcement: if A lists B as synonym, bump score when B lists A
        for other in entries:
            if other.word == entry.word:
                continue
            oid = w2id.get(other.word)
            if oid is None:
                continue
            if entry.word in _normalize_list(other.synonyms):
                add_edge(src_id, oid, SYNONYM_SCORE)
            if entry.word in _normalize_list(other.antonyms):
                add_edge(src_id, oid, ANTONYM_SCORE)

    return [
        WordEdge(id=i + 1, word_id_a=a, word_id_b=b, relation_score=score)
        for i, ((a, b), score) in enumerate(sorted(edge_map.items()))
    ]


def extract_category_relations(
    categories: list[CategoryNode],
    entries: list[WordDictEntry],
    rules: list[KeywordRule],
) -> list[CategoryEdge]:
    """Directed category edges with ontology_relation labels."""
    c2id = category_name_to_id(categories)
    raw_edges: list[tuple[int, int, str, float]] = []

    def add_directed(
        source_name: str,
        target_name: str,
        relation: str,
        score: float,
        *,
        symmetric: bool = False,
    ) -> None:
        src_id = c2id.get(source_name)
        tgt_id = c2id.get(target_name)
        if src_id is None or tgt_id is None or src_id == tgt_id:
            return
        if symmetric:
            src_id, tgt_id = symmetric_edge_ids(src_id, tgt_id)
        raw_edges.append((src_id, tgt_id, relation, score))

    for cat in categories:
        if cat.parent_category:
            add_directed(
                cat.category_name,
                cat.parent_category,
                "is_a",
                PARENT_CHILD_CATEGORY_SCORE,
            )

    by_parent: dict[str, list[str]] = {}
    for cat in categories:
        if cat.parent_category:
            by_parent.setdefault(cat.parent_category, []).append(cat.category_name)

    for siblings in by_parent.values():
        for i, a in enumerate(siblings):
            for b in siblings[i + 1 :]:
                add_directed(a, b, "sibling_of", SIBLING_CATEGORY_SCORE, symmetric=True)

    opposing_pairs = [
        ("positive", "negative"),
        ("magnitude_high", "magnitude_low"),
        ("rate_high", "rate_low"),
        ("thermal_high", "thermal_low"),
        ("ability_high", "ability_low"),
    ]
    for a, b in opposing_pairs:
        add_directed(a, b, "opposite_of", OPPOSING_SECONDARY_CATEGORY_SCORE, symmetric=True)

    primary_tags: dict[str, set[str]] = {}
    for entry in entries:
        if entry.primary_category:
            primary_tags.setdefault(entry.primary_category, set()).update(entry.category_tags)

    shared_tag_groups: dict[str, list[str]] = {}
    for primary, tags in primary_tags.items():
        for tag in tags:
            shared_tag_groups.setdefault(tag, []).append(primary)

    shared_tag_score = SIBLING_CATEGORY_SCORE * 0.6
    for primaries in shared_tag_groups.values():
        for i, a in enumerate(primaries):
            for b in primaries[i + 1 :]:
                add_directed(a, b, "shares_domain_tag", shared_tag_score, symmetric=True)

    for source, target, relation, score in infer_relations_from_entries(entries, categories, rules):
        add_directed(source, target, relation, score)

    edge_map = merge_directed_edges(raw_edges)
    return [
        CategoryEdge(
            id=i + 1,
            category_id_a=src,
            category_id_b=tgt,
            relation_score=score,
            ontology_relation=relation,
        )
        for i, ((src, tgt, relation), score) in enumerate(sorted(edge_map.items()))
    ]


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def convert(
    dict_data_dir: Path,
    output_dir: Path,
    *,
    keywords_seed: Path | None = None,
    progress_callback: Callable[[str, int, int, int], None] | None = None,
) -> dict[str, Path]:
    def emit(phase: str, current: int, total: int, percent: int) -> None:
        if progress_callback:
            progress_callback(phase, current, total, percent)

    emit("starting", 0, 1, 0)
    keywords = load_keyword_rules(keywords_seed)
    emit("loading_dict_files", 0, 1, 2)

    total_files = len(sorted(dict_data_dir.glob("*.txt")))
    entries = load_dict_files(
        dict_data_dir,
        rules=keywords,
        progress_callback=(
            lambda current, total: emit(
                "parsing_files",
                current,
                total,
                2 + int((max(1, current) / max(1, total)) * 70),
            )
        )
        if total_files
        else None,
    )
    if not entries:
        raise ValueError(f"No .txt dict files found in {dict_data_dir}")

    emit("building_graph", 0, 1, 75)
    categories = extract_categories(entries)
    words = build_word_nodes(entries)
    apply_word_risk_overrides(words, load_word_risk_overrides(dict_data_dir))
    risk_overrides = load_category_risk_overrides(dict_data_dir)
    apply_category_risk_levels(categories, words, risk_overrides)
    word_edges = extract_word_relations(entries, words, keywords)
    category_edges = extract_category_relations(categories, entries, keywords)
    word_categories = build_word_category_assignments(words)
    explicit_pairs = load_word_pair_seeds(dict_data_dir)
    word_pairs = build_word_pair_levels(words, word_edges, explicit_pairs)
    emit("writing_csv", 0, 1, 88)

    paths = {
        "categories": output_dir / "categories.csv",
        "words": output_dir / "words.csv",
        "edges": output_dir / "edges.csv",
        "category_relations": output_dir / "category_relations.csv",
        "keywords": output_dir / "keywords.csv",
        "word_categories": output_dir / "word_categories.csv",
        "word_pairs": output_dir / "word_pairs.csv",
    }

    write_csv(
        paths["categories"],
        ["id", "parent_category", "category_name", "category_level", "default_risk_level"],
        [
            {
                "id": c.id,
                "parent_category": c.parent_category,
                "category_name": c.category_name,
                "category_level": c.category_level,
                "default_risk_level": c.default_risk_level if c.default_risk_level is not None else "",
            }
            for c in categories
        ],
    )
    write_csv(
        paths["words"],
        [
            "id",
            "word",
            "meaning",
            "primary_category",
            "secondary_category",
            "pos",
            "register",
            "domain",
            "risk_level",
            "category_tags",
        ],
        [
            {
                "id": w.id,
                "word": w.word,
                "meaning": w.meaning,
                "primary_category": w.primary_category,
                "secondary_category": w.secondary_category,
                "pos": w.pos,
                "register": w.register,
                "domain": w.domain,
                "risk_level": w.risk_level if w.risk_level is not None else "",
                "category_tags": ";".join(w.category_tags),
            }
            for w in words
        ],
    )
    write_csv(
        paths["edges"],
        ["id", "word_id_a", "word_id_b", "relation_score"],
        [
            {
                "id": e.id,
                "word_id_a": e.word_id_a,
                "word_id_b": e.word_id_b,
                "relation_score": e.relation_score,
            }
            for e in word_edges
        ],
    )
    write_csv(
        paths["category_relations"],
        ["id", "category_id_a", "category_id_b", "relation_score", "ontology_relation"],
        [
            {
                "id": e.id,
                "category_id_a": e.category_id_a,
                "category_id_b": e.category_id_b,
                "relation_score": e.relation_score,
                "ontology_relation": e.ontology_relation,
            }
            for e in category_edges
        ],
    )
    write_csv(
        paths["word_categories"],
        ["word_id", "category_name", "role"],
        [
            {
                "word_id": a.word_id,
                "category_name": a.category_name,
                "role": a.role,
            }
            for a in word_categories
        ],
    )
    write_csv(
        paths["word_pairs"],
        ["id", "word_a", "word_b", "risk_level", "source"],
        [
            {
                "id": i + 1,
                "word_a": p.word_a,
                "word_b": p.word_b,
                "risk_level": p.risk_level,
                "source": p.source,
            }
            for i, p in enumerate(word_pairs)
        ],
    )
    save_keywords_csv(paths["keywords"], keywords)
    emit("done", 1, 1, 100)

    return paths
