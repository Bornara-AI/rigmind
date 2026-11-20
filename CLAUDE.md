# RigMind — project context for Claude

## What this is
RigMind is a GenAI operations copilot for oil and gas. Field engineers and operations managers ask plain-English questions about (1) company documents (regulations, safety and operating procedures) and (2) well production data. Every answer cites its sources; the app says "I don't know" instead of guessing.

It is a portfolio project that demonstrates:
- Python backends: Django + Django REST Framework, FastAPI
- GenAI done properly: RAG, hallucination handling, agents with tools, evaluations, guardrails, observability, cost control
- Production practice: tests, CI/CD, Docker, cloud deployment, logging
- Maintainability: a repo a new contributor could join in a day (docs, ADRs, review checklist)

## Tech stack
| Layer | Choice |
|---|---|
| Product API | Django 5 + Django REST Framework, djangorestframework-simplejwt, drf-spectacular |
| AI service | FastAPI, Pydantic v2, uvicorn, async |
| Agent | LangGraph (tool calling); RAG itself is plain Python + SQL, no LangChain/LlamaIndex (ADR 0002) |
| LLM / embeddings | OpenAI (provider-agnostic interface so Azure OpenAI can be swapped in) |
| Database | PostgreSQL 16 + pgvector (app data, production data, vectors in one DB) |
| Background jobs | Celery + Redis (PDF ingestion, daily briefing) |
| Frontend | React + TypeScript (Vite), streaming via Server-Sent Events |
| Observability | Langfuse (or OpenTelemetry) traces: prompt, chunks, tokens, cost, latency |
| Evals | Ragas or a custom pytest scorer; golden set of 30–50 Q&A pairs |
| Tooling | uv (or pip) + pyproject.toml, ruff, black, mypy (light), pytest, pre-commit |
| Infra | Docker Compose locally; Azure Container Apps; GitHub Actions CI/CD |

## Architecture
- React calls **Django** for users, roles, documents and production data (REST + JWT).
- React calls **FastAPI** for questions, data questions and the agent (answers streamed via SSE).
- FastAPI verifies Django-issued JWTs (shared signing key), reads chunks from pgvector, calls the LLM.
- Celery workers ingest PDFs: parse → chunk → embed → store in pgvector.
- Django owns the database schema and migrations. FastAPI reads app tables via SQLAlchemy (read-only for app tables); FastAPI may write only its own tables (e.g. `ai_query_log`, `ai_feedback`).

## Repo layout (target)
```
rigmind/
  backend_django/        # Django project: config/, apps/users, apps/documents, apps/production
  ai_service/            # FastAPI: app/main.py, app/api/, app/rag/, app/agent/, app/guardrails/, app/evals/
  worker/                # Celery tasks (may live inside backend_django)
  frontend/              # React + TypeScript (Vite)
  data/                  # sample PDFs (public) + production data generator script
  evals/                 # golden_set.jsonl, eval runner
  docs/adr/              # Architecture Decision Records
  docker-compose.yml
  .github/workflows/ci.yml
  CLAUDE.md  README.md  CONTRIBUTING.md  ROADMAP.md
```

## Data
Full plan: `docs/DATA_PLAN.md` (sources, pipeline, seeded data, licence). Decision: `docs/adr/0001-use-public-alberta-data.md`.
- **Real data first.** Production/wells/operators come from Petrinex Alberta public data (monthly CSV downloads, current + previous 4 years): Conventional Volumetrics, Well Infrastructure, Well Licence, Well to Facility Link, Business Associate, code reports. Regulations come from AER directive PDFs (keep page numbers).
- **Pipeline:** `data/raw/` (git-ignored) → `stg_*` tables (text, COPY) → clean tables (`wells`, `production_monthly` well × month × product, `facility_activity_monthly`) → views (`v_well_monthly` with oil_m3, gas_e3m3, water_m3, hours, GOR, water cut). IDs stay text; masked `***` → NULL + flag; idempotent upsert; lineage (source_file) on every row.
- **Seeded (fictional, `random.Random(42)`, `manage.py seed_demo`) only for:** demo company + users per role, watchlist of ~50 real wells, role-restricted internal documents, a prompt-injection PDF, a daily ops/downtime log (`data/generate_ops.py`), Petrinex-layout test fixtures, eval golden set.
- Roles: `field_engineer`, `ops_manager`, `admin`. Each document has allowed roles.
- Credit sources on every page; don't redistribute raw source files.

## GenAI requirements (the core of the project)
**RAG**
- Chunk by headings/paragraphs, ~500–800 tokens, overlap; metadata: document_id, title, page, section, allowed_roles.
- Hybrid search: pgvector cosine + PostgreSQL full-text; merge (reciprocal rank fusion); retrieve top 20 → re-rank → top 5.
- Filter by the user's role BEFORE anything reaches the LLM.
- Answers cite sources as [1], [2] mapped to document/page/passage.

**Hallucination handling**
- Grounded system prompt: answer only from sources; otherwise say so.
- Retrieval threshold: below a minimum score, return "not found in the documents" without calling the LLM.
- Groundedness check: a cheap model verifies each sentence against cited chunks; unsupported sentences are removed or flagged.
- Citation validation in code: every cited index exists and the quoted text is in that chunk.
- All LLM outputs are Pydantic models (answer, citations, confidence), validated, retried once on invalid output.

**Agent**
- LangGraph agent with tools: `search_documents`, `query_production` (read-only SQL), `calculate_decline`, `draft_report`.
- Limits: max 6 steps, timeout, cost cap per request. Log every tool call.
- Human in the loop: reports are drafts until a user approves them.

**Text-to-SQL safety**
- Dedicated read-only DB user; allowlist of tables/columns; `SELECT` only; enforced LIMIT; parse/validate SQL before running (sqlglot); show the SQL to the user.

**Guardrails / security**
- Document text is data, never instructions (prompt-injection test PDF in the eval set).
- No secrets in code; `.env` locally, Key Vault / app settings in Azure.
- Rate limit AI endpoints per user.

**Quality, cost, ops**
- Eval suite runs in CI on every change to prompts or retrieval; track retrieval hit rate, faithfulness, answer relevance.
- Prompts are versioned files (`ai_service/app/prompts/*.md` with a version header).
- Trace every request: prompt version, chunk ids, tokens, cost, latency.
- Cache repeated questions; small model for checks, larger model for answers.

## Conventions
- Python 3.12, type hints everywhere, ruff + black, f-strings, `pathlib`, no bare `except`.
- Settings via environment variables (`pydantic-settings` in FastAPI, `django-environ` in Django).
- REST: plural nouns, proper status codes, pagination on lists, OpenAPI docs always up to date.
- Tests: pytest (+ pytest-django); every endpoint has at least a happy-path and an auth test; LLM calls are mocked in unit tests.
- Commits: small, imperative ("Add hybrid search to retriever"). Commit at least daily.
- Every significant choice gets a short ADR in `docs/adr/` (context, decision, consequences).
- Never commit `.env`, API keys or real company data.

## Commands (fill in as they are created)
- `docker compose up --build` — run everything
- `docker compose exec django python manage.py migrate`
- `docker compose exec django pytest` / `docker compose exec ai pytest`
- `docker compose exec django python -m petrinex.download vol --from 2024-09 --to 2026-08` (also `infra "Well Infrastructure"`, `codes`; `--force` to re-download) — files go to `data/raw/petrinex/` (git-ignored)
- `docker compose exec django python manage.py load_petrinex --from 2024-09 --to 2026-08` — load downloaded months (replaces each month)
- `docker compose exec django python manage.py createsuperuser` — then browse http://localhost:8000/admin/
- `python evals/run.py` — run the evaluation suite

## Definition of done (per feature)
Works in Docker Compose · has tests · OpenAPI updated · logged/traced · README or ADR updated if behaviour or architecture changed · committed and pushed.

## Current status
Update this line at the end of each session: **M0 done — Compose (db/redis/django/ai), both health endpoints + tests, CI, pre-commit. M1 done: `petrinex.download` CLI + `petrinex.read.iter_rows()` (streams the nested zip, 51 MB peak on a 120 MB month), 46 tests, fixture `tests/fixtures/petrinex/vol_2026-08_sample.csv`. ADR 0002 (no RAG framework). M2 in progress: custom `users.User` (role), `production` app + `load_petrinex` (COPY → staging → replace month), 24 months loaded (2024-09 → 2026-08), 61 tests.** Next: Well Infrastructure reader + `wells` + `v_well_monthly`, then `documents` app and `seed_demo`.
