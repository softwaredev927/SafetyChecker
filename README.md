# SafetyChecker

Dictionary ontology builder with CSV storage, FastAPI admin API, and a React review UI.

## Components

| Path | Description |
|------|-------------|
| `dictgraph/` | Convert `.txt` dictionaries → CSV graphs; CLI search |
| `safety_api/` | FastAPI: convert, search, and direct safety score updates |
| `web/` | React UI for convert, search, edit tools, and direct score updates |
| `data/` | Runtime audit log (created on first use) |

## Quick start

### 1. Python API

```bash
cd c:\PrivWork\SafetyChecker
pip install -r requirements.txt
python -m dictgraph convert
uvicorn safety_api.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

### 2. React web app

```bash
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173 — Vite proxies `/api` to the backend.

## Safety score workflow

Safety score changes are applied immediately through `POST /api/v1/safety/apply`.
Each update rewrites source data, regenerates output CSVs, and appends an audit row.

Changes are persisted to:

- **Words** — `Risk_level` in `dict_data/{word}.txt`, or `word_risk_overrides.csv`
- **Categories** — `category_risk_overrides.csv`
- **Word pairs** — `word_pairs_seed.csv`

Audit events append to `data/audit_log.csv`.

## Key API routes

- `POST /api/v1/convert` — rebuild output CSVs
- `GET /api/v1/search/words` — word search (query, tier, domain, category)
- `GET /api/v1/search/categories` — category search
- `GET /api/v1/search/category-tree` — hierarchy
- `POST /api/v1/safety/apply` — apply score and regenerate

## CLI (unchanged)

```bash
python -m dictgraph convert
python -m dictgraph search --words attack --tier high
```
