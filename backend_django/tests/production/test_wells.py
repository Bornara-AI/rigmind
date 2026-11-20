from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.production.loading import (
    load_volumetric_file,
    load_wells_file,
    unmatched_production_wells,
)
from apps.production.models import Well
from tests.helpers import (
    VOL_FIXTURE,
    WELLS_FIXTURE,
    fixture_rows,
    nested_zip,
    to_csv_bytes,
    wells_zip,
)

pytestmark = pytest.mark.django_db

SOURCE = "infra/well-infrastructure.zip"


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    wells_zip(tmp_path)
    nested_zip(VOL_FIXTURE.read_bytes(), tmp_path / "vol")
    return tmp_path


def load_wells(dest: Path) -> None:
    load_wells_file(dest / SOURCE, source_file=SOURCE)


def load_production(dest: Path) -> None:
    load_volumetric_file(dest / "vol/2026-08.zip", "2026-08", "vol/2026-08.zip")


# --- wells ------------------------------------------------------------------


def test_one_well_per_well_id_with_linked_facilities_merged(dest: Path) -> None:
    load_wells(dest)

    assert Well.objects.count() == 10
    well = Well.objects.get(well_id="ABWI100010206504W400")
    assert well.uwi == "100/01-02-065-04W4/00"
    assert well.linked_facility_ids == ["ABBT0051211", "ABIF0008797"]
    assert well.licensee_name == "IMPERIAL OIL RESOURCES LIMITED"
    assert well.source_file == SOURCE


def test_well_without_linked_facility_gets_empty_list(dest: Path) -> None:
    load_wells(dest)

    assert Well.objects.get(well_id="ABWI100010100813W400").linked_facility_ids == []


def test_reload_upserts_changes(dest: Path) -> None:
    load_wells(dest)
    fieldnames, rows = fixture_rows(WELLS_FIXTURE)
    for row in rows:
        if row["WellID"] == "ABWI100120505319W502":
            row["LicenseeName"] = "NEW OWNER LTD"
    wells_zip(dest, to_csv_bytes(fieldnames, rows))

    load_wells(dest)

    assert Well.objects.count() == 10
    assert Well.objects.get(well_id="ABWI100120505319W502").licensee_name == (
        "NEW OWNER LTD"
    )


def test_reports_production_wells_without_a_well_record(dest: Path) -> None:
    load_production(dest)
    fieldnames, rows = fixture_rows(WELLS_FIXTURE)
    without = [r for r in rows if r["WellID"] != "ABWI102151406806W600"]
    wells_zip(dest, to_csv_bytes(fieldnames, without))

    load_wells(dest)

    assert unmatched_production_wells() == ["ABWI102151406806W600"]


# --- v_well_monthly ---------------------------------------------------------


def fetch_well_month(well_id: str) -> dict[str, object]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM v_well_monthly WHERE well_id = %s AND month = '2026-08-01'",
            [well_id],
        )
        columns = [c.name for c in cursor.description]
        return dict(zip(columns, cursor.fetchone(), strict=True))


def test_view_pivots_products_and_computes_ratios(dest: Path) -> None:
    load_wells(dest)
    load_production(dest)

    row = fetch_well_month("ABWI100010206504W400")

    assert row["uwi"] == "100/01-02-065-04W4/00"
    assert row["oil_m3"] == Decimal("5.2")
    assert row["gas_e3m3"] == Decimal("0.3")
    assert row["water_m3"] == Decimal("50.7")
    assert row["cond_m3"] is None
    assert row["hours_on"] == 106
    assert row["gor_m3_m3"] == Decimal("57.7")  # 0.3 e3m3 * 1000 / 5.2 m3
    assert row["water_cut"] == Decimal("0.9070")  # 50.7 / (5.2 + 50.7)


def test_view_has_no_gor_without_oil(dest: Path) -> None:
    load_wells(dest)
    load_production(dest)

    row = fetch_well_month("ABWI100120505319W502")  # gas only, two facilities

    assert row["gas_e3m3"] == Decimal("3513.1")
    assert row["oil_m3"] is None
    assert row["gor_m3_m3"] is None
    assert row["water_cut"] is None


# --- command ----------------------------------------------------------------


def test_command_loads_wells_and_reports_matches(dest: Path) -> None:
    load_production(dest)
    out = StringIO()

    call_command("load_wells", "--dest", str(dest), stdout=out)

    assert "11 rows staged, 10 wells upserted" in out.getvalue()
    assert "All production wells have a well record." in out.getvalue()


def test_command_fails_without_file(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="not found"):
        call_command("load_wells", "--dest", str(tmp_path))
