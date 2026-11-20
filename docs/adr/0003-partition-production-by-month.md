# ADR 0003: Partition production tables by month

**Status:** Proposed, 2026-11-20 (to decide in M12, with the monthly refresh)

## Context
`load_petrinex` replaces a whole month on every load: `DELETE` the month, then `INSERT` it again from staging (see DATA_PLAN §3). That is correct for amended months, but in PostgreSQL a `DELETE` only marks rows dead; space and index entries are reclaimed later by `VACUUM`.

Measured on `production_monthly` (5.8M rows, 24 months; one month ≈ 243k rows):

| State | Forced reload of 2026-08 |
|---|---|
| Right after `VACUUM (ANALYZE)` (9 s) | 27.0 s |
| With 243k dead rows from the previous reload | 31.7 s |
| With 482k dead rows, cold cache after a restart | 96.9 s (both factors; not separated) |

The monthly refresh re-loads the newest month plus the 3 previous ones (amendments), so dead rows accumulate by about 1M per refresh until autovacuum catches up.

## Decision (proposed)
Declare `production_monthly` and `facility_activity_monthly` as **range-partitioned by `month`**, one partition per month. Replacing a month becomes:

1. `CREATE TABLE ... (LIKE production_monthly INCLUDING ALL)` and fill it from staging;
2. in one transaction: `ALTER TABLE production_monthly DETACH PARTITION <old>`, `ATTACH PARTITION <new> FOR VALUES FROM (month) TO (month + 1)`, `DROP TABLE <old>`.

Django keeps owning the schema: the partitioned parent and the partition-management helper are created in migrations with `RunSQL`; the Django models stay unchanged for reads.

## Consequences
- No dead rows from reloads and no `VACUUM` debt; a month swap is a metadata change readers never see half-done.
- Queries filtered by month prune to one partition.
- Primary keys and unique constraints must include `month` (already true for the natural key `(well_id, month, product)`; the surrogate `id` would become `(id, month)`).
- More moving parts: partitions must exist before loading (create on demand in the loader), and Django's ORM does not create them.
- Until this is done, `load_petrinex` runs `ANALYZE` after loading and relies on autovacuum; the database container gets `shm_size: 256mb` so `VACUUM` and parallel queries have enough shared memory.
