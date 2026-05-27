from __future__ import annotations

from pydantic import BaseModel, Field


class ConvertResponse(BaseModel):
    files: dict[str, str]


class ConvertJobStartResponse(BaseModel):
    job_id: str
    status: str
    percent: int
    phase: str
    current: int
    total: int
    created_at: str
    updated_at: str


class ConvertJobStatusResponse(BaseModel):
    job_id: str
    status: str
    percent: int
    phase: str
    current: int
    total: int
    files: dict[str, str] = Field(default_factory=dict)
    error: str = ""
    created_at: str
    updated_at: str


class SearchCategoriesParams(BaseModel):
    query: str = ""
    subtree: str = ""


class SearchWordsParams(BaseModel):
    query: str = ""
    pos: str = ""
    register: str = ""
    domain: str = ""
    tier: str = ""
    category: str = ""


class DirectScoreUpdate(BaseModel):
    entity_type: str
    entity_key: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str
    actor: str = "admin"


class HealthResponse(BaseModel):
    status: str
    dict_data: str
    output: str
    word_count: int


class KeywordSeed(BaseModel):
    id: int
    keyword: str
    purpose_of_keyword: str
    is_regex: bool = False
    ontology_relation: str = ""


class KeywordSeedCreate(BaseModel):
    keyword: str
    purpose_of_keyword: str
    is_regex: bool = False
    ontology_relation: str = ""
    id: int | None = Field(default=None, description="Optional; auto-assigned if omitted")


class KeywordSeedUpdate(BaseModel):
    keyword: str
    purpose_of_keyword: str
    is_regex: bool = False
    ontology_relation: str = ""


class WordEditUpdate(BaseModel):
    meaning: str = ""
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)
    pos: str = ""
    register: str = ""
    domain: str = ""
    risk_level: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)


class CategoryEditUpdate(BaseModel):
    default_risk_level: float | None = Field(default=None, ge=0.0, le=1.0)


class ApplyWordScoreToSynonymsRequest(BaseModel):
    word: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = "bulk_apply_synonyms"
    actor: str = "admin"


class ApplyCategoryScoreToWordsRequest(BaseModel):
    category: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = "bulk_apply_category_words"
    actor: str = "admin"


class BulkApplyResponse(BaseModel):
    total_targets: int
    updated: int
    skipped: int
    missing: int
