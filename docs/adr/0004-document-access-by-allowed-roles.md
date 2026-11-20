# ADR 0004: Control document access with an `allowed_roles` list, with no admin bypass

**Status:** Accepted, 2026-11-20

## Context
Some documents are public regulations (AER directives); others are internal and meant for certain roles only (for example, an incident report for operations managers). A field engineer must never see a restricted passage, whether in a document list or inside an AI answer.

Two services read documents: Django (lists, downloads) and FastAPI (retrieval for RAG and the agent). Any access rule has to be written in both, so it must be simple enough that the two copies cannot drift.

Options considered:
- **Per-user or per-group permissions** (Django's permission framework or a sharing table): flexible, but FastAPI would have to replicate joins it does not own, and nobody needs per-user sharing yet.
- **A minimum clearance level** (1, 2, 3): simple, but roles are not ordered. An ops manager is not "more" than a field engineer for every document.
- **A list of allowed roles on each document**: one column and one rule.

## Decision
- Every document has `allowed_roles`: a non-empty PostgreSQL array of role values.
- A user may read a document when `allowed_roles @> ARRAY[user.role]`. No role is special: an admin reads a document only if `admin` is in the list.
- The rule exists once per service: `Document.objects.visible_to(role)` in Django, and the same predicate in FastAPI's retrieval SQL, applied before chunks reach the LLM. Chunks will copy their document's `allowed_roles` so retrieval filters without a join.
- The database enforces the list: a CHECK constraint rejects an empty list and unknown roles, even for raw SQL writes.
- Uploaded files are stored by content hash (`documents/<sha[:2]>/<sha>.pdf`), and the media folder is never served directly. Files are served only through the API, which applies the same rule.

## Consequences
- The rule is one array operator, which is easy to test in both services and fast with a GIN index once the chunks table grows.
- Adding a role means a migration, because the CHECK constraint lists the roles. That is deliberate: a new role should be a reviewed change.
- Admins can see everything only by being listed. Uploaders tick `admin` explicitly, which keeps "who can read this" visible on every document.
- Per-user sharing is not possible. If it is needed later, it can be added alongside the role list without changing the rule for roles.
- Changing a document's roles means re-syncing its chunks' copies. The M5 ingestion task will own that sync.
