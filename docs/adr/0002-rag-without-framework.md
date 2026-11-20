# ADR 0002: Build the RAG pipeline in plain Python and SQL; use LangGraph only for the agent

**Status:** Accepted, 2026-11-20

## Context
RigMind's answers must cite their sources, respect document roles and say "I don't know" when retrieval is weak. The usual shortcuts are LangChain or LlamaIndex, which provide retrievers, vector stores and query engines out of the box.

Constraints from the architecture:
- Django owns the database schema and migrations. LangChain's and LlamaIndex's PostgreSQL vector stores create and manage their own tables.
- Role filtering must happen in the retrieval query, before any text reaches the LLM.
- Retrieval is hybrid (pgvector cosine + PostgreSQL full-text, merged with reciprocal rank fusion), then re-ranked.
- Every request is traced (prompt version, chunk ids, tokens, cost, latency), and LLM outputs are validated Pydantic models with one retry.

## Decision
- **Retrieval:** hand-written SQL over Django-managed tables (`chunks` with an embedding column and a `tsvector` column). One query applies the role filter, runs vector and full-text search, and fuses ranks with RRF (`1 / (60 + rank)`).
- **Chunking:** our own heading/paragraph splitter that keeps document id, page and section on each chunk. A small standalone splitter package may be used for the token-size logic.
- **Re-ranking:** a `Reranker` interface with one implementation (a cross-encoder model or a rerank API), chosen by evals.
- **LLM calls:** the OpenAI SDK behind a small provider interface (so Azure OpenAI can be swapped in), with Pydantic structured outputs.
- **Agent (M10):** LangGraph, for its state graph, tool calling, step limits and human-approval interrupts. The agent's `search_documents` tool calls the same retrieval code as `/ask`.
- **Evals:** Ragas or a custom pytest scorer, independent of any RAG framework.

## Consequences
- More code to write and test in M6–M8: splitter, hybrid query, RRF, prompt assembly, citation checks.
- Full control and visibility: each step is plain, unit-testable code and appears in traces under our own names.
- The schema stays in Django migrations; no framework-owned tables in the database.
- We pick up `langchain-core` indirectly through LangGraph, but we don't use LangChain chains or retrievers.
- If we later need connectors for many document types, we can revisit LlamaIndex for ingestion only, behind the existing chunk table.
