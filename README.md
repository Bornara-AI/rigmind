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

## Roadmap

See [ROADMAP.md](ROADMAP.md).
