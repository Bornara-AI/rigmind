# ADR 0001: Use real public Alberta data, seed only what is missing

**Status:** Accepted, 2026-11-18

## Context
RigMind needs production data and regulations. Fake data would make the demo less credible. Alberta publishes monthly well/facility volumetrics (Petrinex public data, the last 5 years) and its regulations (AER directives) for free.

## Decision
- Production, well and operator data come from Petrinex Alberta public downloads, loaded through raw → staging → clean tables with lineage.
- Regulations come from AER directive PDFs.
- Seeded, clearly fictional data is used only for users and roles, internal documents (to test access control), daily operations logs, test fixtures and evals.
- Sources are credited on every page; each dataset is used under its publisher's terms.

## Consequences
- More ETL work (M1–M2) and a file layout we must verify against real files.
- Confidential volumes are masked by the source, so some wells have gaps; the UI must show that rather than hide it.
- Tests use local fixtures, never the network.
