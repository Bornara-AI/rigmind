from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.production.loading import load_volumetric_file
from apps.production.models import (
    Facility,
    FacilityActivityMonthly,
    Operator,
    PetrinexLoad,
    ProductionMonthly,
)
from tests.helpers import VOL_FIXTURE, fixture_rows, nested_zip, to_csv_bytes

pytestmark = pytest.mark.django_db

AUG = date(2026, 8, 1)
SOURCE = "vol/2026-08.zip"


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    nested_zip(VOL_FIXTURE.read_bytes(), tmp_path / "vol")
    return tmp_path


def load(dest: Path) -> None:
    load_volumetric_file(dest / SOURCE, "2026-08", source_file=SOURCE)


def production(well_id: str, product: str) -> ProductionMonthly:
    return ProductionMonthly.objects.get(well_id=well_id, month=AUG, product=product)


# --- production_monthly -----------------------------------------------------


def test_loads_one_row_per_well_month_product(dest: Path) -> None:
    load(dest)

    assert ProductionMonthly.objects.count() == 6
    oil = production("ABWI100010206504W400", "OIL")
    assert oil.volume == Decimal("5.2")
    assert oil.hours == 106
    assert oil.facility_ids == ["ABBT0051211"]
    assert oil.submission_date == date(2026, 10, 20)
    assert oil.source_file == SOURCE


def test_duplicate_well_rows_are_summed(dest: Path) -> None:
    load(dest)

    gas = production("ABWI100120505319W502", "GAS")
    assert gas.volume == Decimal("1246.6") + Decimal("2266.5")
    assert gas.hours == 456
    assert gas.facility_ids == ["ABBT0088921", "ABBT0174444"]


def test_masked_hours_are_flagged(dest: Path) -> None:
    load(dest)

    cond = production("ABWI102151406806W600", "COND")
    assert cond.hours is None
    assert cond.is_masked is True


# --- flare / vent / fuel, operators, facilities -----------------------------


def test_loads_flare_vent_fuel_activity(dest: Path) -> None:
    load(dest)

    rows = FacilityActivityMonthly.objects.filter(month=AUG)
    assert sorted(rows.values_list("activity", flat=True)) == ["FLARE", "FUEL", "VENT"]
    fuel = rows.get(activity="FUEL")
    assert fuel.facility_id == "ABBT3710049"
    assert fuel.energy == Decimal("4644.0")


def test_upserts_operators_and_facilities(dest: Path) -> None:
    load(dest)

    assert Operator.objects.count() == 5
    assert Operator.objects.get(baid="0150").name == "MEDICINE HAT, CITY OF"
    assert Facility.objects.count() == 7
    battery = Facility.objects.get(facility_id="ABBT0051211")
    assert battery.operator_id == "0007"
    assert battery.facility_type == "BT"


# --- idempotency and lineage ------------------------------------------------


def test_forced_rerun_replaces_the_month(dest: Path) -> None:
    load(dest)
    load_volumetric_file(dest / SOURCE, "2026-08", source_file=SOURCE, force=True)

    assert ProductionMonthly.objects.count() == 6
    assert FacilityActivityMonthly.objects.count() == 3
    assert PetrinexLoad.objects.count() == 2


def test_unchanged_file_is_skipped(dest: Path) -> None:
    load(dest)

    result = load_volumetric_file(dest / SOURCE, "2026-08", source_file=SOURCE)

    assert result.skipped is True
    assert PetrinexLoad.objects.count() == 1
    assert ProductionMonthly.objects.count() == 6


def test_staging_table_is_unlogged() -> None:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relpersistence FROM pg_class WHERE relname = 'stg_volumetric'"
        )
        assert cursor.fetchone() == ("u",)


def test_amended_file_removes_rows_that_disappeared(dest: Path) -> None:
    load(dest)
    fieldnames, rows = fixture_rows()
    without_oil = [
        r
        for r in rows
        if not (r["FromToID"] == "ABWI100010206504W400" and r["ProductID"] == "OIL")
    ]
    nested_zip(to_csv_bytes(fieldnames, without_oil), dest / "vol")

    load(dest)

    assert not ProductionMonthly.objects.filter(
        well_id="ABWI100010206504W400", product="OIL"
    ).exists()
    assert ProductionMonthly.objects.count() == 5


def test_records_a_load_with_counts(dest: Path) -> None:
    load(dest)

    record = PetrinexLoad.objects.get()
    assert record.month == AUG
    assert record.rows_staged == 10
    assert record.production_rows == 6
    assert record.activity_rows == 3
    assert len(record.sha256) == 64


def test_rejects_rows_for_another_month(dest: Path) -> None:
    with pytest.raises(ValueError, match="not for month 2026-07"):
        load_volumetric_file(dest / SOURCE, "2026-07", source_file=SOURCE)

    assert ProductionMonthly.objects.count() == 0


# --- management command -----------------------------------------------------


def test_command_loads_month(dest: Path) -> None:
    out = StringIO()
    call_command("load_petrinex", "--month", "2026-08", "--dest", str(dest), stdout=out)

    assert "2026-08: 10 rows staged, 6 production, 3 flare/vent/fuel" in out.getvalue()


def test_command_skips_unchanged_month_unless_forced(dest: Path) -> None:
    args = ["load_petrinex", "--month", "2026-08", "--dest", str(dest)]
    call_command(*args, stdout=StringIO())

    skipped, forced = StringIO(), StringIO()
    call_command(*args, stdout=skipped)
    call_command(*args, "--force", stdout=forced)

    assert "unchanged since the last load, skipped" in skipped.getvalue()
    assert "10 rows staged" in forced.getvalue()
    assert PetrinexLoad.objects.count() == 2


def test_command_fails_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="1 of 1 months failed"):
        call_command(
            "load_petrinex",
            "--month",
            "2026-08",
            "--dest",
            str(tmp_path),
            stderr=StringIO(),
        )


def test_command_requires_month_or_range() -> None:
    with pytest.raises(CommandError, match="either --month"):
        call_command("load_petrinex")
