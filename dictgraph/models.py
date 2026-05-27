from dataclasses import dataclass, field

from typing import Any





@dataclass

class WordDictEntry:

    word: str

    meaning: str

    synonyms: list[str] = field(default_factory=list)

    antonyms: list[str] = field(default_factory=list)

    primary_category: str = ""

    secondary_category: str = ""

    category_tags: list[str] = field(default_factory=list)

    pos: str = ""

    register: str = ""

    domain: str = ""

    risk_level: float | None = None

    source_file: str = ""



    @classmethod

    def from_dict(cls, data: dict[str, Any], source_file: str = "") -> "WordDictEntry":

        risk_raw = data.get("risk_level")

        risk_level: float | None = None

        if risk_raw is not None and str(risk_raw).strip() != "":

            risk_level = max(0.0, min(1.0, float(risk_raw)))



        return cls(

            word=str(data.get("word", "")).strip().lower(),

            meaning=str(data.get("meaning", "")).strip(),

            synonyms=[str(s).strip().lower() for s in data.get("synonyms", [])],

            antonyms=[str(a).strip().lower() for a in data.get("antonyms", [])],

            primary_category=str(data.get("primary_category", "")).strip().lower(),

            secondary_category=str(data.get("secondary_category", "")).strip().lower(),

            category_tags=[str(t).strip().lower() for t in data.get("category_tags", [])],

            pos=str(data.get("pos", "")).strip().lower(),

            register=str(data.get("register", "")).strip().lower(),

            domain=str(data.get("domain", "")).strip().lower(),

            risk_level=risk_level,

            source_file=source_file,

        )



    def is_safety_taxonomy(self) -> bool:
        """Safety tree applies when register or domain is set (not headword POS alone)."""
        return bool(self.register or self.domain)





@dataclass

class KeywordRule:

    id: int

    keyword: str

    purpose_of_keyword: str

    is_regex: bool = False

    ontology_relation: str = ""





@dataclass

class CategoryNode:

    id: int

    parent_category: str

    category_name: str

    category_level: int = 0

    default_risk_level: float | None = None





@dataclass

class WordNode:

    id: int

    word: str

    meaning: str

    primary_category: str

    secondary_category: str

    pos: str = ""

    register: str = ""

    domain: str = ""

    risk_level: float | None = None

    category_tags: list[str] = field(default_factory=list)





@dataclass

class WordEdge:

    id: int

    word_id_a: int

    word_id_b: int

    relation_score: float





@dataclass

class CategoryEdge:

    id: int

    category_id_a: int

    category_id_b: int

    relation_score: float

    ontology_relation: str = ""





@dataclass

class WordPairLevel:

    word_a: str

    word_b: str

    risk_level: float

    source: str = "explicit"





@dataclass

class WordCategoryAssignment:

    word_id: int

    category_name: str

    role: str

