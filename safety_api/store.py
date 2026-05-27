"""CSV-backed database: ontology output, seed overrides, and audit."""

from __future__ import annotations

import csv
import re
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from dictgraph.converter import convert
from dictgraph.keywords import load_keyword_rules, save_keywords_json
from dictgraph.models import KeywordRule
from dictgraph.search import DictGraphIndex, RISK_TIERS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DICT_DATA = ROOT / "dictgraph" / "dict_data"
DEFAULT_OUTPUT = ROOT / "dictgraph" / "output"
DEFAULT_KEYWORDS_SEED = ROOT / "dictgraph" / "keywords_seed.json"
DEFAULT_DATA_DIR = ROOT / "data"

AUDIT_COLUMNS = [
    "id",
    "entity_type",
    "entity_key",
    "old_score",
    "new_score",
    "reason",
    "actor",
    "approval_id",
    "created_at",
]

REMOVED_KEYWORD_PURPOSES = {
    "primary_category_starter",
    "secondary_category_starter",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 4)))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, keep_default_na=False)


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return df.where(pd.notnull(df), None).to_dict(orient="records")


class CsvSafetyStore:
    def __init__(
        self,
        *,
        dict_data_dir: Path = DEFAULT_DICT_DATA,
        output_dir: Path = DEFAULT_OUTPUT,
        data_dir: Path = DEFAULT_DATA_DIR,
        keywords_seed: Path = DEFAULT_KEYWORDS_SEED,
    ) -> None:
        self.dict_data_dir = Path(dict_data_dir)
        self.output_dir = Path(output_dir)
        self.data_dir = Path(data_dir)
        self.keywords_seed = Path(keywords_seed)
        self.audit_path = self.data_dir / "audit_log.csv"
        self._convert_jobs: dict[str, dict[str, Any]] = {}
        self._convert_jobs_lock = threading.Lock()

    def index(self) -> DictGraphIndex:
        return DictGraphIndex.load(self.output_dir)

    def run_convert(self) -> dict[str, str]:
        paths = convert(self.dict_data_dir, self.output_dir, keywords_seed=self.keywords_seed)
        return {name: str(path) for name, path in paths.items()}

    def start_convert_job(self) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = _utc_now()
        with self._convert_jobs_lock:
            self._convert_jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "percent": 0,
                "phase": "queued",
                "current": 0,
                "total": 1,
                "files": {},
                "error": "",
                "created_at": now,
                "updated_at": now,
            }
        thread = threading.Thread(target=self._run_convert_job, args=(job_id,), daemon=True)
        thread.start()
        return self.get_convert_job(job_id)

    def get_convert_job(self, job_id: str) -> dict[str, Any]:
        with self._convert_jobs_lock:
            if job_id not in self._convert_jobs:
                raise KeyError(f"Convert job not found: {job_id}")
            return dict(self._convert_jobs[job_id])

    def _run_convert_job(self, job_id: str) -> None:
        def update(
            *,
            status: str | None = None,
            percent: int | None = None,
            phase: str | None = None,
            current: int | None = None,
            total: int | None = None,
            files: dict[str, str] | None = None,
            error: str | None = None,
        ) -> None:
            with self._convert_jobs_lock:
                job = self._convert_jobs.get(job_id)
                if job is None:
                    return
                if status is not None:
                    job["status"] = status
                if percent is not None:
                    job["percent"] = max(0, min(100, int(percent)))
                if phase is not None:
                    job["phase"] = phase
                if current is not None:
                    job["current"] = max(0, int(current))
                if total is not None:
                    job["total"] = max(1, int(total))
                if files is not None:
                    job["files"] = files
                if error is not None:
                    job["error"] = error
                job["updated_at"] = _utc_now()

        update(status="running", phase="starting", percent=0, current=0, total=1)
        try:
            paths = convert(
                self.dict_data_dir,
                self.output_dir,
                keywords_seed=self.keywords_seed,
                progress_callback=lambda phase, current, total, percent: update(
                    status="running",
                    phase=phase,
                    current=current,
                    total=total,
                    percent=percent,
                ),
            )
            files = {name: str(path) for name, path in paths.items()}
            update(status="done", phase="done", percent=100, current=1, total=1, files=files)
        except Exception as exc:
            detail = f"{exc}\n{traceback.format_exc()}"
            update(status="error", phase="error", error=detail)

    def tiers(self) -> dict[str, list[float]]:
        return {k: [lo, hi] for k, (lo, hi) in RISK_TIERS.items()}

    def _load_keyword_rules(self) -> list[KeywordRule]:
        return load_keyword_rules(self.keywords_seed)

    def _save_keyword_rules(self, rules: list[KeywordRule]) -> None:
        self.keywords_seed.parent.mkdir(parents=True, exist_ok=True)
        save_keywords_json(self.keywords_seed, rules)

    @staticmethod
    def _keyword_rule_dict(rule: KeywordRule) -> dict[str, Any]:
        return {
            "id": rule.id,
            "keyword": rule.keyword,
            "purpose_of_keyword": rule.purpose_of_keyword,
            "is_regex": rule.is_regex,
            "ontology_relation": rule.ontology_relation,
        }

    @staticmethod
    def _validate_keyword_rule(rule: KeywordRule) -> None:
        if not rule.keyword.strip():
            raise ValueError("keyword must not be empty")
        if not rule.purpose_of_keyword.strip():
            raise ValueError("purpose_of_keyword must not be empty")
        if rule.purpose_of_keyword in REMOVED_KEYWORD_PURPOSES:
            raise ValueError(
                f"purpose_of_keyword '{rule.purpose_of_keyword}' is no longer supported; use category_tags_starter"
            )
        if rule.is_regex:
            try:
                re.compile(rule.keyword)
            except re.error as exc:
                raise ValueError(f"Invalid regex: {exc}") from exc

    def list_keyword_seeds(self) -> list[dict[str, Any]]:
        return [
            self._keyword_rule_dict(rule)
            for rule in self._load_keyword_rules()
            if rule.purpose_of_keyword not in REMOVED_KEYWORD_PURPOSES
        ]

    def get_keyword_seed(self, rule_id: int) -> dict[str, Any] | None:
        for rule in self._load_keyword_rules():
            if rule.id == rule_id:
                if rule.purpose_of_keyword in REMOVED_KEYWORD_PURPOSES:
                    return None
                return self._keyword_rule_dict(rule)
        return None

    def create_keyword_seed(
        self,
        *,
        keyword: str,
        purpose_of_keyword: str,
        is_regex: bool = False,
        ontology_relation: str = "",
        rule_id: int | None = None,
    ) -> dict[str, Any]:
        rules = self._load_keyword_rules()
        next_id = max((rule.id for rule in rules), default=0) + 1
        assigned_id = rule_id if rule_id is not None else next_id
        if any(rule.id == assigned_id for rule in rules):
            raise ValueError(f"Keyword seed id already exists: {assigned_id}")

        rule = KeywordRule(
            id=assigned_id,
            keyword=keyword.strip(),
            purpose_of_keyword=purpose_of_keyword.strip(),
            is_regex=is_regex,
            ontology_relation=ontology_relation.strip(),
        )
        self._validate_keyword_rule(rule)
        rules.append(rule)
        self._save_keyword_rules(sorted(rules, key=lambda item: item.id))
        return self._keyword_rule_dict(rule)

    def update_keyword_seed(
        self,
        rule_id: int,
        *,
        keyword: str,
        purpose_of_keyword: str,
        is_regex: bool = False,
        ontology_relation: str = "",
    ) -> dict[str, Any]:
        rules = self._load_keyword_rules()
        updated: KeywordRule | None = None
        for index, rule in enumerate(rules):
            if rule.id != rule_id:
                continue
            updated = KeywordRule(
                id=rule_id,
                keyword=keyword.strip(),
                purpose_of_keyword=purpose_of_keyword.strip(),
                is_regex=is_regex,
                ontology_relation=ontology_relation.strip(),
            )
            self._validate_keyword_rule(updated)
            rules[index] = updated
            break
        if updated is None:
            raise KeyError(f"Keyword seed not found: {rule_id}")
        self._save_keyword_rules(sorted(rules, key=lambda item: item.id))
        return self._keyword_rule_dict(updated)

    def delete_keyword_seed(self, rule_id: int) -> None:
        rules = self._load_keyword_rules()
        kept = [rule for rule in rules if rule.id != rule_id]
        if len(kept) == len(rules):
            raise KeyError(f"Keyword seed not found: {rule_id}")
        self._save_keyword_rules(kept)

    def _audit_df(self) -> pd.DataFrame:
        df = _read_csv(self.audit_path)
        if df.empty:
            return pd.DataFrame(columns=AUDIT_COLUMNS)
        for col in AUDIT_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df

    def _append_audit(
        self,
        *,
        entity_type: str,
        entity_key: str,
        old_score: float | None,
        new_score: float,
        reason: str,
        actor: str,
        approval_id: str = "",
    ) -> None:
        rows = []
        path = self.audit_path
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "entity_type": entity_type,
                "entity_key": entity_key,
                "old_score": "" if old_score is None else old_score,
                "new_score": new_score,
                "reason": reason,
                "actor": actor,
                "approval_id": approval_id,
                "created_at": _utc_now(),
            }
        )
        _write_csv(path, AUDIT_COLUMNS, rows)

    def _current_word_score(self, word: str) -> float | None:
        idx = self.index()
        if idx.words.empty:
            return None
        match = idx.words[idx.words["word"].str.lower() == word.lower()]
        if match.empty:
            return None
        raw = match.iloc[0].get("risk_level", "")
        if raw == "" or raw is None:
            return None
        return float(raw)

    def _current_category_score(self, category: str) -> float | None:
        idx = self.index()
        if idx.categories.empty:
            return None
        match = idx.categories[
            idx.categories["category_name"].str.lower() == category.lower()
        ]
        if match.empty:
            return None
        raw = match.iloc[0].get("default_risk_level", "")
        if raw == "" or raw is None:
            return None
        return float(raw)

    def _current_pair_score(self, word_a: str, word_b: str) -> float | None:
        a, b = sorted([word_a.lower(), word_b.lower()])
        idx = self.index()
        if idx.word_pairs.empty:
            return None
        mask = (
            (idx.word_pairs["word_a"].str.lower() == a)
            & (idx.word_pairs["word_b"].str.lower() == b)
        ) | (
            (idx.word_pairs["word_a"].str.lower() == b)
            & (idx.word_pairs["word_b"].str.lower() == a)
        )
        match = idx.word_pairs[mask]
        if match.empty:
            return None
        return float(match.iloc[0]["risk_level"])

    def _word_exists(self, token: str) -> bool:
        idx = self.index()
        if idx.words.empty:
            return False
        return not idx.words[idx.words["word"].str.lower() == token.lower()].empty

    def get_word_edit(self, token: str) -> dict[str, Any] | None:
        idx = self.index()
        if idx.words.empty:
            return None
        match = idx.words[idx.words["word"].str.lower() == token.lower()]
        if match.empty:
            return None
        row = match.iloc[0]
        word = str(row.get("word", "")).strip().lower()
        txt_path = self.dict_data_dir / f"{word}.txt"
        synonyms: list[str] = []
        antonyms: list[str] = []
        if txt_path.is_file():
            text = txt_path.read_text(encoding="utf-8")
            syn_match = re.search(r"(?im)^\s*Synonyms\s*:\s*(.*)$", text)
            ant_match = re.search(r"(?im)^\s*Antonyms\s*:\s*(.*)$", text)
            if syn_match:
                synonyms = [item.strip() for item in syn_match.group(1).split(",") if item.strip()]
            if ant_match:
                antonyms = [item.strip() for item in ant_match.group(1).split(",") if item.strip()]
        tags_raw = str(row.get("category_tags", "")).strip()
        tags = [item.strip() for item in re.split(r"[;,]", tags_raw) if item.strip()]
        risk_raw = row.get("risk_level")
        risk_level = None if risk_raw in ("", None) else float(risk_raw)
        return {
            "word": word,
            "meaning": str(row.get("meaning", "")).strip(),
            "synonyms": synonyms,
            "antonyms": antonyms,
            "pos": str(row.get("pos", "")).strip(),
            "register": str(row.get("register", "")).strip(),
            "domain": str(row.get("domain", "")).strip(),
            "risk_level": risk_level,
            "tags": tags,
            "source_file": txt_path.name if txt_path.is_file() else "",
        }

    def update_word_edit(
        self,
        token: str,
        *,
        meaning: str,
        synonyms: list[str],
        antonyms: list[str],
        pos: str,
        register: str,
        domain: str,
        risk_level: float | None,
        tags: list[str],
    ) -> dict[str, Any]:
        token = token.strip().lower()
        if not token:
            raise ValueError("word token must not be empty")
        txt_path = self.dict_data_dir / f"{token}.txt"
        current = self.get_word_edit(token)
        if current is None:
            raise KeyError(f"Word not found: {token}")

        normalized_synonyms = [item.strip() for item in synonyms if item.strip()]
        normalized_antonyms = [item.strip() for item in antonyms if item.strip()]
        normalized_tags = [item.strip() for item in tags if item.strip()]
        risk_text = "" if risk_level is None else f"{_clamp_score(risk_level):.2f}"

        lines = [
            f"Word: {token} — {pos.strip() or 'noun'}",
            "",
            meaning.strip(),
            "",
            f"Synonyms: {', '.join(normalized_synonyms)}",
            f"Antonyms: {', '.join(normalized_antonyms)}",
            "",
            f"POS: {pos.strip()}",
            f"Register: {register.strip()}",
            f"Domain: {domain.strip()}",
            f"Risk_level: {risk_text}",
            f"Tags: {', '.join(normalized_tags)}",
            "",
        ]
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        self.run_convert()
        updated = self.get_word_edit(token)
        if updated is None:
            raise ValueError("Word update failed")
        return updated

    def get_category_edit(self, category: str) -> dict[str, Any] | None:
        idx = self.index()
        if idx.categories.empty:
            return None
        match = idx.categories[idx.categories["category_name"].str.lower() == category.lower()]
        if match.empty:
            return None
        row = match.iloc[0]
        category_name = str(row.get("category_name", "")).strip().lower()
        default_raw = row.get("default_risk_level")
        default_level = None if default_raw in ("", None) else float(default_raw)

        override_level = None
        override_path = self.dict_data_dir / "category_risk_overrides.csv"
        if override_path.is_file():
            with override_path.open(newline="", encoding="utf-8") as f:
                for item in csv.DictReader(f):
                    if str(item.get("category_name", "")).strip().lower() != category_name:
                        continue
                    raw = str(item.get("default_risk_level", "")).strip()
                    if raw:
                        override_level = float(raw)
                    break

        return {
            "category_name": category_name,
            "parent_category": str(row.get("parent_category", "")).strip(),
            "category_level": int(row.get("category_level", 0) or 0),
            "default_risk_level": default_level,
            "override_risk_level": override_level,
            "has_override": override_level is not None,
        }

    def update_category_edit(self, category: str, *, default_risk_level: float | None) -> dict[str, Any]:
        current = self.get_category_edit(category)
        if current is None:
            raise KeyError(f"Category not found: {category}")
        key = str(current["category_name"]).lower()
        path = self.dict_data_dir / "category_risk_overrides.csv"
        headers = ["category_name", "default_risk_level"]
        rows: list[dict[str, Any]] = []
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        kept = [row for row in rows if str(row.get("category_name", "")).strip().lower() != key]
        if default_risk_level is not None:
            kept.append({"category_name": key, "default_risk_level": _clamp_score(default_risk_level)})
        _write_csv(path, headers, kept)
        self.run_convert()
        updated = self.get_category_edit(key)
        if updated is None:
            raise ValueError("Category update failed")
        return updated

    def apply_direct(
        self,
        *,
        entity_type: str,
        entity_key: str,
        score: float,
        reason: str,
        actor: str = "admin",
    ) -> dict[str, Any]:
        """Apply score immediately (skip approval queue) and regenerate CSVs."""
        entity_type = entity_type.lower()
        score = _clamp_score(score)
        key = entity_key.strip().lower()

        if entity_type == "word":
            old = self._current_word_score(key)
            self._apply_word_score(key, score)
        elif entity_type == "category":
            old = self._current_category_score(key)
            self._apply_category_score(key, score)
        elif entity_type == "word_pair":
            parts = [p.strip().lower() for p in key.split(",")]
            if len(parts) != 2:
                raise ValueError("word_pair entity_key must be 'word_a,word_b'")
            key = f"{min(parts[0], parts[1])},{max(parts[0], parts[1])}"
            old = self._current_pair_score(parts[0], parts[1])
            self._apply_word_pair_score(parts[0], parts[1], score)
        else:
            raise ValueError(f"Unknown entity_type: {entity_type}")

        self._append_audit(
            entity_type=entity_type,
            entity_key=key,
            old_score=old,
            new_score=score,
            reason=reason,
            actor=actor,
        )
        paths = self.run_convert()
        return {"entity_type": entity_type, "entity_key": key, "score": score, "paths": paths}

    def apply_word_score_to_synonyms(
        self,
        *,
        word: str,
        score: float,
        reason: str,
        actor: str = "admin",
    ) -> dict[str, Any]:
        source = self.get_word_edit(word)
        if source is None:
            raise KeyError(f"Word not found: {word}")
        score = _clamp_score(score)
        source_word = str(source["word"]).strip().lower()
        targets = sorted(
            {
                item.strip().lower()
                for item in source.get("synonyms", [])
                if item.strip() and item.strip().lower() != source_word
            }
        )
        updated = 0
        skipped = 0
        missing = 0
        for target in targets:
            if not self._word_exists(target):
                missing += 1
                continue
            old = self._current_word_score(target)
            if old is not None and abs(old - score) < 1e-9:
                skipped += 1
                continue
            self._apply_word_score(target, score)
            self._append_audit(
                entity_type="word",
                entity_key=target,
                old_score=old,
                new_score=score,
                reason=reason,
                actor=actor,
            )
            updated += 1
        self.run_convert()
        return {
            "total_targets": len(targets),
            "updated": updated,
            "skipped": skipped,
            "missing": missing,
        }

    def apply_category_score_to_words(
        self,
        *,
        category: str,
        score: float,
        reason: str,
        actor: str = "admin",
    ) -> dict[str, Any]:
        existing = self.get_category_edit(category)
        if existing is None:
            raise KeyError(f"Category not found: {category}")
        category_name = str(existing["category_name"]).strip().lower()
        idx = self.index()
        rows = idx.words_in_category(category_name, include_descendants=False)
        targets = sorted(
            {
                str(record.get("word", "")).strip().lower()
                for record in _df_to_records(rows)
                if str(record.get("word", "")).strip()
            }
        )
        score = _clamp_score(score)
        updated = 0
        skipped = 0
        missing = 0
        for target in targets:
            if not self._word_exists(target):
                missing += 1
                continue
            old = self._current_word_score(target)
            if old is not None and abs(old - score) < 1e-9:
                skipped += 1
                continue
            self._apply_word_score(target, score)
            self._append_audit(
                entity_type="word",
                entity_key=target,
                old_score=old,
                new_score=score,
                reason=reason,
                actor=actor,
            )
            updated += 1
        self.run_convert()
        return {
            "total_targets": len(targets),
            "updated": updated,
            "skipped": skipped,
            "missing": missing,
        }

    def _apply_word_score(self, word: str, score: float) -> None:
        word = word.lower()
        txt_path = self.dict_data_dir / f"{word}.txt"
        if txt_path.is_file() and self._set_risk_in_txt(txt_path, score):
            return
        self._upsert_seed_csv(
            self.dict_data_dir / "word_risk_overrides.csv",
            ["word", "risk_level"],
            "word",
            word,
            {"word": word, "risk_level": score},
        )

    def _set_risk_in_txt(self, path: Path, score: float) -> bool:
        text = path.read_text(encoding="utf-8")
        line_re = re.compile(r"^(\s*Risk_level\s*:\s*)([^\n]*)", re.IGNORECASE | re.MULTILINE)
        new_line = f"Risk_level: {score:.2f}"
        if line_re.search(text):
            updated = line_re.sub(lambda m: m.group(1) + f"{score:.2f}", text, count=1)
        else:
            updated = text.rstrip() + f"\n\n{new_line}\n"
        path.write_text(updated, encoding="utf-8")
        return True

    def _apply_category_score(self, category: str, score: float) -> None:
        self._upsert_seed_csv(
            self.dict_data_dir / "category_risk_overrides.csv",
            ["category_name", "default_risk_level"],
            "category_name",
            category.lower(),
            {"category_name": category.lower(), "default_risk_level": score},
        )

    def _apply_word_pair_score(self, word_a: str, word_b: str, score: float) -> None:
        a, b = sorted([word_a.lower(), word_b.lower()])
        self._upsert_seed_csv(
            self.dict_data_dir / "word_pairs_seed.csv",
            ["word_a", "word_b", "risk_level"],
            None,
            f"{a}|{b}",
            {"word_a": a, "word_b": b, "risk_level": score},
            match_fn=lambda row: (
                row.get("word_a", "").lower() == a and row.get("word_b", "").lower() == b
            ),
        )

    def _upsert_seed_csv(
        self,
        path: Path,
        headers: list[str],
        key_field: str | None,
        key_value: str,
        row: dict[str, Any],
        *,
        match_fn: Any = None,
    ) -> None:
        rows: list[dict[str, Any]] = []
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        updated = False
        for i, existing in enumerate(rows):
            if match_fn and match_fn(existing):
                rows[i] = {h: row.get(h, existing.get(h, "")) for h in headers}
                updated = True
                break
            if key_field and str(existing.get(key_field, "")).lower() == key_value.lower():
                rows[i] = {h: row.get(h, existing.get(h, "")) for h in headers}
                updated = True
                break
        if not updated:
            rows.append({h: row.get(h, "") for h in headers})
        _write_csv(path, headers, rows)

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        df = self._audit_df()
        if df.empty:
            return []
        return _df_to_records(df.sort_values("created_at", ascending=False).head(limit))
