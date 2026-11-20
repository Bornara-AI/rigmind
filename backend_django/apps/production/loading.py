"""Load one Petrinex volumetrics file into the production tables.

Steps (one transaction per month):
1. COPY the filtered, typed rows from petrinex.read into stg_volumetric.
2. Upsert operators and facilities (newest month wins).
3. Replace the month in production_monthly and facility_activity_monthly.

The month is replaced, not merged: Petrinex republishes amended months, and an
amendment can remove rows, which an upsert alone would leave behind.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.db import connection, transaction

from apps.production.models import PetrinexLoad
from petrinex.download import sha256_file
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
