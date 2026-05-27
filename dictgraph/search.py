"""Pandas-based search over dictgraph CSV outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

RISK_TIERS: dict[str, tuple[float, float]] = {
    "very_high": (0.80, 1.00),
    "high": (0.60, 0.80),
    "riskable": (0.40, 0.60),
    "low": (0.20, 0.40),
    "very_low": (0.00, 0.20),
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, keep_default_na=False)


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


@dataclass
class DictGraphIndex:
    categories: pd.DataFrame
    words: pd.DataFrame
    word_categories: pd.DataFrame
    word_pairs: pd.DataFrame
    edges: pd.DataFrame

    @classmethod
    def load(cls, output_dir: Path) -> "DictGraphIndex":
        output_dir = Path(output_dir)
        return cls(
            categories=_read_csv(output_dir / "categories.csv"),
            words=_read_csv(output_dir / "words.csv"),
            word_categories=_read_csv(output_dir / "word_categories.csv"),
            word_pairs=_read_csv(output_dir / "word_pairs.csv"),
            edges=_read_csv(output_dir / "edges.csv"),
        )

    def _category_descendants(self, root: str) -> set[str]:
        if self.categories.empty or "category_name" not in self.categories.columns:
            return set()
        children: dict[str, list[str]] = {}
        for _, row in self.categories.iterrows():
            parent = str(row.get("parent_category", "")).strip()
            name = str(row.get("category_name", "")).strip()
            if parent:
                children.setdefault(parent, []).append(name)

        result: set[str] = set()
        stack = [root.lower()]
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            stack.extend(children.get(current, []))
        return result

    def search_categories(
        self,
        query: str,
        *,
        subtree: str | None = None,
    ) -> pd.DataFrame:
        if self.categories.empty:
            return self.categories.copy()

        df = self.categories.copy()
        mask = df["category_name"].str.contains(query, case=False, na=False)
        if subtree:
            allowed = self._category_descendants(subtree)
            mask &= df["category_name"].str.lower().isin(allowed)
        return df[mask].sort_values("category_name").reset_index(drop=True)

    def categories_by_tier(self, tier: str) -> pd.DataFrame:
        if tier not in RISK_TIERS:
            raise ValueError(f"Unknown tier {tier!r}; expected one of {list(RISK_TIERS)}")

        if self.categories.empty:
            return self.categories.copy()

        lo, hi = RISK_TIERS[tier]
        levels = _numeric_series(self.categories, "default_risk_level")
        if tier == "very_high":
            mask = levels >= lo
        elif tier == "very_low":
            mask = (levels >= lo) & (levels < hi)
        else:
            mask = (levels >= lo) & (levels < hi)
        return self.categories[mask].sort_values("category_name").reset_index(drop=True)

    def words_in_category(
        self,
        category: str,
        *,
        include_descendants: bool = True,
    ) -> pd.DataFrame:
        if self.words.empty:
            return self.words.copy()

        cat = category.strip().lower()
        if include_descendants:
            names = self._category_descendants(cat)
        else:
            names = {cat}

        if self.word_categories.empty:
            mask = pd.Series(False, index=self.words.index)
            for col in ("primary_category", "secondary_category", "pos", "register", "domain"):
                if col in self.words.columns:
                    mask |= self.words[col].str.lower().isin(names)
            if "category_tags" in self.words.columns:
                for name in names:
                    mask |= self.words["category_tags"].str.contains(name, case=False, na=False)
            return self.words[mask].reset_index(drop=True)

        wc = self.word_categories.copy()
        wc["category_name"] = wc["category_name"].str.lower()
        word_ids = wc.loc[wc["category_name"].isin(names), "word_id"].unique()
        return self.words[self.words["id"].isin(word_ids)].reset_index(drop=True)

    def search_words(
        self,
        query: str = "",
        *,
        pos: str | None = None,
        register: str | None = None,
        domain: str | None = None,
        tier: str | None = None,
        category: str | None = None,
    ) -> pd.DataFrame:
        if self.words.empty:
            return self.words.copy()

        df = self.words.copy()
        if query:
            mask = (
                df["word"].str.contains(query, case=False, na=False)
                | df["meaning"].str.contains(query, case=False, na=False)
            )
            if "category_tags" in df.columns:
                mask |= df["category_tags"].str.contains(query, case=False, na=False)
            df = df[mask]

        if pos and "pos" in df.columns:
            df = df[df["pos"].str.lower() == pos.lower()]
        if register and "register" in df.columns:
            df = df[df["register"].str.lower() == register.lower()]
        if domain and "domain" in df.columns:
            df = df[df["domain"].str.lower() == domain.lower()]

        if tier:
            lo, hi = RISK_TIERS[tier]
            levels = _numeric_series(df, "risk_level")
            if tier == "very_high":
                df = df[levels >= lo]
            elif tier == "very_low":
                df = df[(levels >= lo) & (levels < hi)]
            else:
                df = df[(levels >= lo) & (levels < hi)]

        if category:
            in_cat = self.words_in_category(category, include_descendants=True)
            df = df[df["id"].isin(in_cat["id"])]

        return df.reset_index(drop=True)

    def word_pairs_for(self, word: str) -> pd.DataFrame:
        if self.word_pairs.empty:
            return self.word_pairs.copy()

        w = word.strip().lower()
        mask = (self.word_pairs["word_a"].str.lower() == w) | (
            self.word_pairs["word_b"].str.lower() == w
        )
        return self.word_pairs[mask].reset_index(drop=True)

    def category_tree(self, root: str = "lexicon") -> pd.DataFrame:
        if self.categories.empty:
            return pd.DataFrame(columns=["category_name", "parent_category", "path", "category_level"])

        children: dict[str, list[str]] = {}
        meta: dict[str, dict] = {}
        for _, row in self.categories.iterrows():
            name = str(row["category_name"]).strip()
            parent = str(row.get("parent_category", "")).strip()
            meta[name] = {
                "parent_category": parent,
                "category_level": row.get("category_level", ""),
                "default_risk_level": row.get("default_risk_level", ""),
            }
            if parent:
                children.setdefault(parent, []).append(name)

        root_key = root.strip().lower()
        if root_key not in meta and root_key != "":
            return pd.DataFrame(columns=["category_name", "parent_category", "path", "category_level"])

        rows: list[dict] = []

        def walk(name: str, prefix: str) -> None:
            info = meta[name]
            path = f"{prefix}/{name}" if prefix else name
            rows.append(
                {
                    "category_name": name,
                    "parent_category": info["parent_category"],
                    "path": path,
                    "category_level": info["category_level"],
                    "default_risk_level": info["default_risk_level"],
                }
            )
            for child in sorted(children.get(name, [])):
                walk(child, path)

        if root_key == "":
            for node in sorted(n for n, p in meta.items() if not p["parent_category"]):
                walk(node, "")
        else:
            walk(root_key, "")

        return pd.DataFrame(rows)
