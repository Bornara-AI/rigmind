from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from petrinex.infra import WellRow, format_uwi, iter_wells
from tests.helpers import wells_zip


@pytest.fixture
def wells(tmp_path: Path) -> list[WellRow]:
    return list(iter_wells(wells_zip(tmp_path)))


def by_id(wells: list[WellRow], well_id: str) -> list[WellRow]:
    return [w for w in wells if w.well_id == well_id]


@pytest.mark.parametrize(
    ("identifier", "uwi"),
    [
        ("100010206504W400", "100/01-02-065-04W4/00"),
        ("102151406806W600", "102/15-14-068-06W6/00"),
        ("100083405026W402", "100/08-34-050-26W4/02"),
    ],
)
def test_format_uwi(identifier: str, uwi: str) -> None:
    assert format_uwi(identifier) == uwi


def test_format_uwi_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="16 characters"):
        format_uwi("10001020650")


def test_reads_every_row_including_one_per_linked_facility(
    wells: list[WellRow],
) -> None:
    assert len(wells) == 11
    linked = sorted(w.linked_facility_id for w in by_id(wells, "ABWI100010206504W400"))
    assert linked == ["ABBT0051211", "ABIF0008797"]


def test_parses_typed_values(wells: list[WellRow]) -> None:
    [peyto] = by_id(wells, "ABWI100120505319W502")

    assert peyto.uwi == "100/12-05-053-19W5/02"
    assert peyto.well_name == "PEYTO EDSON 12-5-53-19"
    assert peyto.drill_direction == "HORIZONTAL"
    assert isinstance(peyto.spud_date, date)
    assert isinstance(peyto.total_depth_m, Decimal)
    assert peyto.is_masked is False


def test_masked_pool_becomes_blank_and_flagged(wells: list[WellRow]) -> None:
    [ovintiv] = by_id(wells, "ABWI102151406806W600")
    assert ovintiv.pool_code == ""
    assert ovintiv.pool_name == ""
    assert ovintiv.is_masked is True


def test_mixed_case_codes_are_upper_cased(wells: list[WellRow]) -> None:
    [well] = by_id(wells, "ABWI100010401728W400")
    assert well.drill_direction == "VERTICAL"
    assert well.licence_status == "RECCERTIFIED"


def test_orphan_flag(wells: list[WellRow]) -> None:
    [orphan] = by_id(wells, "ABWI100010100813W400")
    assert orphan.is_orphan is True
    assert sum(w.is_orphan for w in wells) == 1
