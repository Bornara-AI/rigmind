import zipfile
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from petrinex.read import VolumetricRow, is_relevant, iter_rows
from tests.helpers import VOL_FIXTURE as FIXTURE
from tests.helpers import fixture_rows, nested_zip, to_csv_bytes

TOTAL_ROWS = 17


def edited_fixture(**changes: tuple[int, str, str]) -> bytes:
    """Fixture bytes with edits: name=(row_index, column, new_value)."""
    fieldnames, rows = fixture_rows()
    for row_index, column, value in changes.values():
        rows[row_index][column] = value
    return to_csv_bytes(fieldnames, rows)


@pytest.fixture
def sample_zip(tmp_path: Path) -> Path:
    return nested_zip(FIXTURE.read_bytes(), tmp_path)


@pytest.fixture
def rows(sample_zip: Path) -> list[VolumetricRow]:
    return list(iter_rows(sample_zip))


def well_rows(rows: list[VolumetricRow], well_id: str) -> dict[str, VolumetricRow]:
    return {r.product_id: r for r in rows if r.from_to_id == well_id}


# --- filtering --------------------------------------------------------------


def test_keeps_well_production_and_flare_vent_fuel(rows: list[VolumetricRow]) -> None:
    assert Counter(r.activity_id for r in rows) == {
        "PROD": 7,
        "FLARE": 1,
        "VENT": 1,
        "FUEL": 1,
    }


def test_keep_none_returns_every_row(sample_zip: Path) -> None:
    assert len(list(iter_rows(sample_zip, keep=None))) == TOTAL_ROWS


@pytest.mark.parametrize(
    ("activity", "from_to_type", "expected"),
    [
        ("PROD", "WI", True),
        ("PROD", "BT", False),
        ("FLARE", "BT", True),
        ("VENT", "WI", True),
        ("FUEL", "", True),
        ("DISP", "", False),
        ("ROYALTY", "WI", False),
        ("", "", False),
    ],
)
def test_is_relevant(activity: str, from_to_type: str, expected: bool) -> None:
    raw = {"ActivityID": activity, "FromToIDType": from_to_type}
    assert is_relevant(raw) is expected


# --- parsing ----------------------------------------------------------------


def test_parses_typed_values(rows: list[VolumetricRow]) -> None:
    oil = well_rows(rows, "ABWI100010206504W400")["OIL"]

    assert oil.production_month == "2026-08"
    assert oil.reporting_facility_id == "ABBT0051211"
    assert oil.submission_date == date(2026, 10, 20)
    assert oil.from_to_id_type == "WI"
    assert oil.volume == Decimal("5.2")
    assert oil.hours == 106
    assert oil.energy is None
    assert oil.is_masked is False


def test_ids_keep_leading_zeros(rows: list[VolumetricRow]) -> None:
    oil = well_rows(rows, "ABWI100010206504W400")["OIL"]
    assert oil.operator_baid == "0007"


def test_blank_hours_become_none_without_mask_flag(rows: list[VolumetricRow]) -> None:
    gas = well_rows(rows, "ABWI100010206504W400")["GAS"]
    assert gas.hours is None
    assert gas.is_masked is False


def test_masked_hours_become_none_with_mask_flag(rows: list[VolumetricRow]) -> None:
    cond = well_rows(rows, "ABWI102151406806W600")["COND"]
    assert cond.hours is None
    assert cond.volume == Decimal("315.0")
    assert cond.is_masked is True


def test_quoted_comma_keeps_columns_aligned(rows: list[VolumetricRow]) -> None:
    gas = well_rows(rows, "ABWI100010101506W400")["GAS"]
    assert gas.operator_name == "MEDICINE HAT, CITY OF"
    assert gas.volume == Decimal("4.3")
    assert gas.hours == 743


def test_duplicate_well_rows_are_all_kept(rows: list[VolumetricRow]) -> None:
    duplicates = [r for r in rows if r.from_to_id == "ABWI100120505319W502"]
    assert sorted(r.reporting_facility_id for r in duplicates) == [
        "ABBT0088921",
        "ABBT0174444",
    ]


def test_energy_is_parsed_on_fuel_rows(rows: list[VolumetricRow]) -> None:
    [fuel] = [r for r in rows if r.activity_id == "FUEL"]
    assert fuel.energy == Decimal("4644.0")


# --- file layouts and errors ------------------------------------------------


def test_reads_plain_zip_with_csv_inside(tmp_path: Path) -> None:
    path = tmp_path / "plain.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Vol_2026-08-AB.CSV", FIXTURE.read_bytes())

    assert len(list(iter_rows(path))) == 10


def test_missing_column_raises(tmp_path: Path) -> None:
    header, *body = FIXTURE.read_text(encoding="utf-8").splitlines()
    broken = "\r\n".join([header.replace("Volume", "Vol"), *body])
    path = nested_zip(broken.encode("utf-8"), tmp_path)

    with pytest.raises(ValueError, match="Volume"):
        list(iter_rows(path))


def test_bad_number_raises_with_line_number(tmp_path: Path) -> None:
    data = edited_fixture(bad=(1, "Volume", "abc"))
    path = nested_zip(data, tmp_path)

    with pytest.raises(ValueError, match=r"line 3: not a number: 'abc'"):
        list(iter_rows(path))
