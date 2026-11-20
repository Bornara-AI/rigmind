# RigMind

RigMind is a GenAI operations copilot for oil and gas. Field engineers and operations managers ask plain-English questions about company documents (regulations, safety and operating procedures) and well production data. Every answer cites its sources, and when the documents don't contain the answer, RigMind says "I don't know" instead of guessing. It is a portfolio project that shows production-grade RAG, hallucination handling, a tool-calling agent, evaluations and observability on a Django + FastAPI stack.

## Architecture

- **React + TypeScript** frontend (Vite); answers stream over Server-Sent Events.
- **Django + DRF** (`backend_django/`, port 8000): users, roles, documents and production data; issues JWTs; owns the schema and migrations.
- **FastAPI** (`ai_service/`, port 8001): RAG, text-to-SQL and the LangGraph agent; verifies Django-issued JWTs.
- **PostgreSQL 16 + pgvector**: app data, production data and embeddings in one database.
- **Celery + Redis**: background PDF ingestion (parse → chunk → embed → store) and the daily briefing.

## Run locally

Requires Docker Desktop.

```bash
cp .env.example .env          # then edit values
docker compose up --build
```

Check that both services are up:

```bash
curl http://localhost:8000/api/health   # Django  -> {"status":"ok"}
curl http://localhost:8001/health       # FastAPI -> {"status":"ok"}
```

FastAPI's interactive docs are at http://localhost:8001/docs.

Run the tests:

```bash
docker compose exec django pytest
docker compose exec ai pytest
```

## Load real production data

RigMind runs on public Alberta data from [Petrinex](https://www.petrinex.gov.ab.ca) (see [docs/DATA_PLAN.md](docs/DATA_PLAN.md)). Raw files are downloaded to `data/raw/` and never committed.

```bash
docker compose exec django python manage.py migrate
docker compose exec django python -m petrinex.download vol --from 2024-09 --to 2026-08
docker compose exec django python manage.py load_petrinex --from 2024-09 --to 2026-08
docker compose exec django python -m petrinex.download infra "Well Infrastructure"
docker compose exec django python manage.py load_wells
```

Each month takes about 30 seconds to load; rerunning a month replaces it, and unchanged files are skipped. Wells take about 90 seconds. Per-well monthly production with GOR and water cut is in the `v_well_monthly` view.

## Add documents

Upload PDFs in the admin (http://localhost:8000/admin/, after `createsuperuser`) or from the command line:

```bash
docker compose exec django python manage.py add_document /data/docs/directive-060.pdf   --title "Upstream Petroleum Industry Flaring, Incinerating, and Venting"   --kind regulation --reference "Directive 060"   --roles field_engineer ops_manager admin
```

Each document lists the roles that may read it; answers never use passages a user's role can't see ([ADR 0004](docs/adr/0004-document-access-by-allowed-roles.md)). Files are stored by content hash in `data/uploads/` (git-ignored), and the same file can't be added twice.

## Roadmap

See [ROADMAP.md](ROADMAP.md).
