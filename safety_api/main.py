"""FastAPI server: convert, search, and direct safety score updates."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from safety_api.schemas import (
    ApplyCategoryScoreToWordsRequest,
    ApplyWordScoreToSynonymsRequest,
    BulkApplyResponse,
    CategoryEditUpdate,
    ConvertJobStartResponse,
    ConvertJobStatusResponse,
    DirectScoreUpdate,
    HealthResponse,
    KeywordSeed,
    KeywordSeedCreate,
    KeywordSeedUpdate,
    WordEditUpdate,
)
from safety_api.store import CsvSafetyStore

_ROOT = Path(__file__).resolve().parents[1]

store = CsvSafetyStore(
    dict_data_dir=Path(os.environ.get("DICT_DATA_DIR", str(_ROOT / "dictgraph" / "dict_data"))),
    output_dir=Path(os.environ.get("OUTPUT_DIR", str(_ROOT / "dictgraph" / "output"))),
    data_dir=Path(os.environ.get("DATA_DIR", str(_ROOT / "data"))),
    keywords_seed=Path(os.environ.get("KEYWORDS_SEED", str(_ROOT / "dictgraph" / "keywords_seed.json"))),
)

REMOVED_WORD_COLUMNS = {"primary_category", "secondary_category"}


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    return [{k: v for k, v in row.items() if k not in REMOVED_WORD_COLUMNS} for row in records]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not store.output_dir.joinpath("words.csv").is_file():
        store.run_convert()
    yield


app = FastAPI(
    title="SafetyChecker API",
    description="CSV-backed dictgraph convert, search, and direct safety score updates.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    idx = store.index()
    return HealthResponse(
        status="ok",
        dict_data=str(store.dict_data_dir),
        output=str(store.output_dir),
        word_count=len(idx.words),
    )


@app.get("/api/v1/meta/tiers")
def risk_tiers() -> dict[str, list[float]]:
    return store.tiers()


@app.get("/api/v1/meta/keywords", response_model=list[KeywordSeed])
def list_keyword_seeds() -> list[dict[str, Any]]:
    return store.list_keyword_seeds()


@app.get("/api/v1/meta/keywords/{rule_id}", response_model=KeywordSeed)
def get_keyword_seed(rule_id: int) -> dict[str, Any]:
    row = store.get_keyword_seed(rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Keyword seed not found: {rule_id}")
    return row


@app.post("/api/v1/meta/keywords", response_model=KeywordSeed, status_code=201)
def create_keyword_seed(body: KeywordSeedCreate) -> dict[str, Any]:
    try:
        return store.create_keyword_seed(
            keyword=body.keyword,
            purpose_of_keyword=body.purpose_of_keyword,
            is_regex=body.is_regex,
            ontology_relation=body.ontology_relation,
            rule_id=body.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/v1/meta/keywords/{rule_id}", response_model=KeywordSeed)
def update_keyword_seed(rule_id: int, body: KeywordSeedUpdate) -> dict[str, Any]:
    try:
        return store.update_keyword_seed(
            rule_id,
            keyword=body.keyword,
            purpose_of_keyword=body.purpose_of_keyword,
            is_regex=body.is_regex,
            ontology_relation=body.ontology_relation,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/meta/keywords/{rule_id}", status_code=204)
def delete_keyword_seed(rule_id: int) -> None:
    try:
        store.delete_keyword_seed(rule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/convert", response_model=ConvertJobStartResponse)
def run_convert() -> ConvertJobStartResponse:
    job = store.start_convert_job()
    job_id = str(job.get("job_id", "")).strip()
    if not job_id:
        raise HTTPException(status_code=500, detail="Convert job failed to start.")
    return ConvertJobStartResponse(
        job_id=job_id,
        status=str(job.get("status", "queued")),
        percent=int(job.get("percent", 0)),
        phase=str(job.get("phase", "queued")),
        current=int(job.get("current", 0)),
        total=int(job.get("total", 1)),
        created_at=str(job.get("created_at", "")),
        updated_at=str(job.get("updated_at", "")),
    )


@app.get("/api/v1/convert/{job_id}", response_model=ConvertJobStatusResponse)
def convert_status(job_id: str) -> ConvertJobStatusResponse:
    try:
        return ConvertJobStatusResponse(**store.get_convert_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/search/categories")
def search_categories(
    query: str = Query(""),
    subtree: str = Query(""),
) -> list[dict[str, Any]]:
    idx = store.index()
    return _records(idx.search_categories(query, subtree=subtree or None))


@app.get("/api/v1/search/categories/tier/{tier}")
def categories_by_tier(tier: str) -> list[dict[str, Any]]:
    idx = store.index()
    try:
        return _records(idx.categories_by_tier(tier))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/search/words")
def search_words(
    query: str = Query(""),
    pos: str = Query(""),
    register: str = Query(""),
    domain: str = Query(""),
    tier: str = Query(""),
    category: str = Query(""),
) -> list[dict[str, Any]]:
    idx = store.index()
    return _records(
        idx.search_words(
            query,
            pos=pos or None,
            register=register or None,
            domain=domain or None,
            tier=tier or None,
            category=category or None,
        )
    )


@app.get("/api/v1/search/words/in-category")
def words_in_category(
    category: str = Query(...),
    exact: bool = Query(False),
) -> list[dict[str, Any]]:
    idx = store.index()
    return _records(idx.words_in_category(category, include_descendants=not exact))


@app.get("/api/v1/search/word-pairs")
def word_pairs(word: str = Query(...)) -> list[dict[str, Any]]:
    idx = store.index()
    return _records(idx.word_pairs_for(word))


@app.get("/api/v1/search/category-tree")
def category_tree(root: str = Query("lexicon")) -> list[dict[str, Any]]:
    idx = store.index()
    return _records(idx.category_tree(root))


@app.get("/api/v1/words/{token}")
def get_word(token: str) -> dict[str, Any]:
    idx = store.index()
    if idx.words.empty:
        raise HTTPException(status_code=404, detail="No words loaded")
    match = idx.words[idx.words["word"].str.lower() == token.lower()]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Word not found: {token}")
    return _records(match)[0]


@app.get("/api/v1/edit/words/{token}")
def get_word_edit(token: str) -> dict[str, Any]:
    row = store.get_word_edit(token)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Word not found: {token}")
    return row


@app.put("/api/v1/edit/words/{token}")
def update_word_edit(token: str, body: WordEditUpdate) -> dict[str, Any]:
    try:
        return store.update_word_edit(
            token,
            meaning=body.meaning,
            synonyms=body.synonyms,
            antonyms=body.antonyms,
            pos=body.pos,
            register=body.register,
            domain=body.domain,
            risk_level=body.risk_level,
            tags=body.tags,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/edit/categories/{category}")
def get_category_edit(category: str) -> dict[str, Any]:
    row = store.get_category_edit(category)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Category not found: {category}")
    return row


@app.put("/api/v1/edit/categories/{category}")
def update_category_edit(category: str, body: CategoryEditUpdate) -> dict[str, Any]:
    try:
        return store.update_category_edit(category, default_risk_level=body.default_risk_level)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/safety/apply")
def apply_score_direct(body: DirectScoreUpdate) -> dict[str, Any]:
    try:
        return store.apply_direct(
            entity_type=body.entity_type,
            entity_key=body.entity_key,
            score=body.score,
            reason=body.reason,
            actor=body.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/safety/bulk/synonyms", response_model=BulkApplyResponse)
def apply_score_to_synonyms(body: ApplyWordScoreToSynonymsRequest) -> dict[str, Any]:
    try:
        return store.apply_word_score_to_synonyms(
            word=body.word,
            score=body.score,
            reason=body.reason,
            actor=body.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/safety/bulk/category-words", response_model=BulkApplyResponse)
def apply_score_to_category_words(body: ApplyCategoryScoreToWordsRequest) -> dict[str, Any]:
    try:
        return store.apply_category_score_to_words(
            category=body.category,
            score=body.score,
            reason=body.reason,
            actor=body.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/safety/audit")
def audit_log(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
    return store.audit_log(limit=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("safety_api.main:app", host="0.0.0.0", port=8000, reload=True)
