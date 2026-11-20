"""Load one Petrinex volumetrics file into the production tables.

Steps (one transaction per month):
1. COPY the filtered, typed rows from petrinex.read into stg_volumetric.
2. Upsert operators and facilities (newest month wins).
3. Replace the month in production_monthly and facility_activity_monthly.

The month is replaced, not merged: Petrinex republishes amended months, and an
amendment can remove rows, which an upsert alone would leave behind.
"""

import logging
from dataclasses import dataclass, fields
from datetime import date
from operator import attrgetter
from pathlib import Path

from django.db import connection, transaction

from apps.production.models import PetrinexLoad
from petrinex.download import sha256_file
from petrinex.infra import WellRow, iter_wells
from petrinex.read import VolumetricRow, iter_rows

logger = logging.getLogger(__name__)

STAGING_COLUMNS = (
    "production_month",
    "operator_baid",
    "operator_name",
    "reporting_facility_id",
    "reporting_facility_type",
    "reporting_facility_name",
    "reporting_facility_subtype",
    "submission_date",
    "activity_id",
    "product_id",
    "from_to_id",
    "from_to_id_type",
    "volume",
    "energy",
    "hours",
    "is_masked",
)

UPSERT_OPERATORS = """
INSERT INTO operators (baid, name, last_seen_month)
SELECT DISTINCT ON (operator_baid) operator_baid, operator_name, production_month
FROM stg_volumetric
ORDER BY operator_baid, submission_date DESC NULLS LAST
ON CONFLICT (baid) DO UPDATE
SET name = EXCLUDED.name, last_seen_month = EXCLUDED.last_seen_month
WHERE operators.last_seen_month <= EXCLUDED.last_seen_month
"""

UPSERT_FACILITIES = """
INSERT INTO facilities
    (facility_id, name, facility_type, subtype, operator_baid, last_seen_month)
SELECT DISTINCT ON (reporting_facility_id)
    reporting_facility_id, reporting_facility_name, reporting_facility_type,
    reporting_facility_subtype, operator_baid, production_month
FROM stg_volumetric
ORDER BY reporting_facility_id, submission_date DESC NULLS LAST
ON CONFLICT (facility_id) DO UPDATE
SET name = EXCLUDED.name,
    facility_type = EXCLUDED.facility_type,
    subtype = EXCLUDED.subtype,
    operator_baid = EXCLUDED.operator_baid,
    last_seen_month = EXCLUDED.last_seen_month
WHERE facilities.last_seen_month <= EXCLUDED.last_seen_month
"""

INSERT_PRODUCTION = """
INSERT INTO production_monthly
    (well_id, month, product, volume, hours, facility_ids, is_masked,
     submission_date, source_file)
SELECT from_to_id, production_month, product_id, SUM(volume), MAX(hours),
       array_agg(DISTINCT reporting_facility_id ORDER BY reporting_facility_id),
       bool_or(is_masked), MAX(submission_date), %(source_file)s
FROM stg_volumetric
WHERE activity_id = 'PROD' AND from_to_id_type = 'WI' AND from_to_id IS NOT NULL
GROUP BY from_to_id, production_month, product_id
"""

INSERT_ACTIVITY = """
INSERT INTO facility_activity_monthly
    (facility_id, month, activity, product, from_to_id, from_to_id_type, volume,
     energy, hours, is_masked, submission_date, source_file)
SELECT reporting_facility_id, production_month, activity_id, product_id,
       COALESCE(from_to_id, ''), COALESCE(MAX(from_to_id_type), ''),
       SUM(volume), SUM(energy), MAX(hours), bool_or(is_masked),
       MAX(submission_date), %(source_file)s
FROM stg_volumetric
WHERE activity_id IN ('FLARE', 'VENT', 'FUEL')
GROUP BY reporting_facility_id, production_month, activity_id, product_id,
         COALESCE(from_to_id, '')
"""


@dataclass(frozen=True)
class LoadResult:
    month: date
    rows_staged: int
    production_rows: int
    activity_rows: int
    skipped: bool = False  # True if the file matched the last load of this month


def month_start(month: str) -> date:
    """ "2026-08" -> date(2026, 8, 1)."""
    return date.fromisoformat(f"{month}-01")


def _staging_tuple(row: VolumetricRow) -> tuple[object, ...]:
    """Row values in STAGING_COLUMNS order; the month string becomes a date."""
    rest = (getattr(row, column) for column in STAGING_COLUMNS[1:])
    return (month_start(row.production_month), *rest)


def last_loaded_sha256(month: date) -> str | None:
    """SHA-256 of the most recent load of this month, if any."""
    return (
        PetrinexLoad.objects.filter(month=month)
        .order_by("-loaded_at")
        .values_list("sha256", flat=True)
        .first()
    )


def analyze_production_tables() -> None:
    """Refresh planner statistics after replacing months (many deletes/inserts)."""
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE production_monthly, facility_activity_monthly")


def load_volumetric_file(
    zip_path: Path, month: str, source_file: str, *, force: bool = False
) -> LoadResult:
    """Load one month from zip_path. Rerunning the same month replaces it.

    Skips the load if the file is identical (SHA-256) to the last load of this
    month, unless force is True.
    """
    first_day = month_start(month)
    params = {"month": first_day, "source_file": source_file}
    digest = sha256_file(zip_path)

    if not force and last_loaded_sha256(first_day) == digest:
        logger.info("Skip %s: unchanged since the last load", source_file)
        return LoadResult(first_day, 0, 0, 0, skipped=True)

    with transaction.atomic(), connection.cursor() as cursor:
        # Serialize loads: they share the staging table.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('load_petrinex'))")
        cursor.execute("TRUNCATE stg_volumetric")

        rows_staged = 0
        columns = ", ".join(STAGING_COLUMNS)
        with cursor.copy(f"COPY stg_volumetric ({columns}) FROM STDIN") as copy:
            for row in iter_rows(zip_path):
                copy.write_row(_staging_tuple(row))
                rows_staged += 1

        cursor.execute(
            "SELECT COUNT(*) FROM stg_volumetric WHERE production_month <> %(month)s",
            params,
        )
        (other_months,) = cursor.fetchone()
        if other_months:
            raise ValueError(
                f"{source_file}: {other_months} rows are not for month {month}"
            )

        cursor.execute(UPSERT_OPERATORS)
        cursor.execute(UPSERT_FACILITIES)

        cursor.execute("DELETE FROM production_monthly WHERE month = %(month)s", params)
        cursor.execute(INSERT_PRODUCTION, params)
        production_rows = cursor.rowcount

        cursor.execute(
            "DELETE FROM facility_activity_monthly WHERE month = %(month)s", params
        )
        cursor.execute(INSERT_ACTIVITY, params)
        activity_rows = cursor.rowcount

        cursor.execute("TRUNCATE stg_volumetric")

        PetrinexLoad.objects.create(
            month=first_day,
            source_file=source_file,
            sha256=digest,
            rows_staged=rows_staged,
            production_rows=production_rows,
            activity_rows=activity_rows,
        )

    result = LoadResult(first_day, rows_staged, production_rows, activity_rows)
    logger.info("Loaded %s: %s", source_file, result)
    return result


# --- Wells (Petrinex Well Infrastructure) ----------------------------------

WELL_STAGING_COLUMNS = tuple(f.name for f in fields(WellRow))
# wells columns copied 1:1 from staging (linked_facility_ids is aggregated)
WELL_COLUMNS = tuple(
    c
    for c in WELL_STAGING_COLUMNS
    if c not in ("linked_facility_id", "linked_start_date")
)

UPSERT_WELLS = f"""
INSERT INTO wells ({", ".join(WELL_COLUMNS)}, linked_facility_ids, source_file)
SELECT DISTINCT ON (s.well_id) {", ".join(f"s.{c}" for c in WELL_COLUMNS)},
       links.facility_ids, %(source_file)s
FROM stg_wells s
JOIN (
    SELECT well_id,
           COALESCE(
               array_agg(DISTINCT linked_facility_id ORDER BY linked_facility_id)
                   FILTER (WHERE linked_facility_id <> ''),
               '{{}}'
           ) AS facility_ids
    FROM stg_wells
    GROUP BY well_id
) links USING (well_id)
ORDER BY s.well_id, s.linked_start_date DESC NULLS LAST
ON CONFLICT (well_id) DO UPDATE
SET {", ".join(f"{c} = EXCLUDED.{c}" for c in WELL_COLUMNS[1:])},
    linked_facility_ids = EXCLUDED.linked_facility_ids,
    source_file = EXCLUDED.source_file
"""

UNMATCHED_PRODUCTION_WELLS = """
SELECT p.well_id
FROM (SELECT DISTINCT well_id FROM production_monthly) p
LEFT JOIN wells w USING (well_id)
WHERE w.well_id IS NULL
ORDER BY p.well_id
"""


@dataclass(frozen=True)
class WellLoadResult:
    rows_staged: int
    wells: int


def load_wells_file(zip_path: Path, source_file: str) -> WellLoadResult:
    """Upsert every well in a Well Infrastructure zip (one transaction).

    Wells are reference data that other tables point at, so they are upserted
    rather than replaced. Wells missing from a newer file are kept.
    """
    getters = [attrgetter(c) for c in WELL_STAGING_COLUMNS]
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('load_wells'))")
        cursor.execute("TRUNCATE stg_wells")

        rows_staged = 0
        columns = ", ".join(WELL_STAGING_COLUMNS)
        with cursor.copy(f"COPY stg_wells ({columns}) FROM STDIN") as copy:
            for row in iter_wells(zip_path):
                copy.write_row([get(row) for get in getters])
                rows_staged += 1

        cursor.execute(UPSERT_WELLS, {"source_file": source_file})
        wells = cursor.rowcount
        cursor.execute("TRUNCATE stg_wells")
        cursor.execute("ANALYZE wells")

    result = WellLoadResult(rows_staged, wells)
    logger.info("Loaded %s: %s", source_file, result)
    return result


def unmatched_production_wells() -> list[str]:
    """Well IDs that have production rows but no row in wells."""
    with connection.cursor() as cursor:
        cursor.execute(UNMATCHED_PRODUCTION_WELLS)
        return [well_id for (well_id,) in cursor.fetchall()]
