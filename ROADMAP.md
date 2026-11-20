# RigMind roadmap

Milestones in build order. Data sources and pipeline: [docs/DATA_PLAN.md](docs/DATA_PLAN.md) · decisions: [docs/adr/](docs/adr/).

## M0 — Skeleton ✅
- [x] Docker Compose: PostgreSQL 16 + pgvector, Redis, Django, FastAPI
- [x] `GET /api/health` (Django) and `GET /health` (FastAPI) with tests; CI; pre-commit (ruff, black)

## M1 — Petrinex data ingestion
- [x] Inspect the real files (findings in DATA_PLAN §2): zip-in-zip, ~530k rows/month, well rows = `WI` + `PROD`, IDs join 100% to Well Infrastructure
- [x] `petrinex.download` CLI (vol / infra / codes; skip existing, retry, manifest with SHA-256)
- [x] `petrinex.read.iter_rows()`: stream rows from the nested zip with `csv` + dataclasses; filter well PROD + FLARE/VENT/FUEL
- [x] Fixtures cut from the real files + tests (quoted comma, masked `***`, duplicate well, blank hours); no network

## M2 — Domain models and loading (Django)
- [ ] Apps: `users` (custom user + role), `documents` (allowed_roles, upload), `production` (Well, Facility, Operator, ProductionMonthly, FacilityActivityMonthly, staging)
- [ ] `load_petrinex`: COPY into staging, idempotent upsert, lineage columns; last 24 months
- [ ] `seed_demo`: demo company, users per role, watchlist of ~50 real wells

## M3 — Product API (DRF)
- [ ] JWT (simplejwt), role permissions, drf-spectacular docs, pagination
- [ ] Wells search (UWI / licence / licensee), well monthly production (cumulative, GOR, water cut), documents
- [ ] pytest-django: happy-path and auth tests for every endpoint

## M4 — AI service (FastAPI)
- [ ] Settings, verify Django-issued JWTs, `/ask` stub, OpenAPI, tests

## M5 — Document ingestion
- [ ] Celery + Redis: PDF → pages → chunks (metadata) → embeddings → pgvector
- [ ] AER directives (007, M011, 017, 060, 013, 020, 036, 071), seeded internal docs, prompt-injection test PDF

## M6 — RAG v1
- [ ] Retriever, grounded prompt, citations (directive + page), SSE streaming to a React chat page

## M7 — Retrieval quality
- [ ] Hybrid search (full-text + vector, RRF), re-ranking, role filter before the LLM

## M8 — Hallucination handling
- [ ] Retrieval threshold, groundedness check, citation validation, Pydantic outputs with retry, "I don't know" UI

## M9 — Ask the data
- [ ] Text-to-SQL on production views: read-only user, allowlist, sqlglot validation, LIMIT; answers cite the source file and month; table + chart

## M10 — Agent
- [ ] LangGraph agent: `search_documents`, `query_production`, `calculate_decline` (Arps + EUR), `draft_report`; step/time/cost limits; human approval of reports
- [ ] Seeded daily downtime log consistent with real monthly hours
- [ ] "Is well X flaring above Directive 060 limits?" (data + regulation)

## M11 — Evals
- [ ] Golden set (30+ incl. unanswerable, role-restricted, prompt-injection) on a frozen snapshot; eval runner; GitHub Actions job

## M12 — Observability, guardrails, cost
- [ ] Langfuse / OpenTelemetry traces, rate limiting, caching, eval dashboard
- [ ] Monthly Petrinex refresh (Celery beat, re-load amended months)

## M13 — Release
- [ ] Deploy (Azure Container Apps), demo video, README with results and numbers
- [ ] Source credits on every page
- [ ] CONTRIBUTING.md, review checklist, ADRs, "good first issue" labels
