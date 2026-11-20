"""Read the Petrinex Well Infrastructure report (one row per well x linked facility).

A well linked to two facilities (e.g. a battery and an injection system) appears
twice with identical well attributes; the loader merges them into one well.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from petrinex.read import MASK, RawRow, iter_raw_rows, parse_date, parse_decimal

REQUIRED_COLUMNS = frozenset(
    {
        "WellID",
        "WellIdentifier",
        "WellName",
        "LicenceNumber",
        "LicenseeID",
        "LicenseeName",
        "LinkedFacilityID",
        "LinkedStartDate",
        "Field",
        "FieldName",
        "AreaName",
        "PoolDeposit",
        "PoolDepositName",
        "WellStatusFluid",
        "WellStatusMode",
        "WellStatusType",
        "WellStatusDate",
        "SpudDate",
        "HorizontalDrill",
        "FinalTotalDepth",
        "ConfidentialType",
        "LicenceStatus",
        "OrphanWellFlg",
    }
)
MASKABLE_COLUMNS = ("PoolDeposit", "PoolDepositName")


@dataclass(frozen=True, slots=True)
class WellRow:
    """One Well Infrastructure row. Text is stripped ("" if blank or masked)."""

    well_id: str  # e.g. ABWI100010206504W400
    uwi: str  # e.g. 100/01-02-065-04W4/00
    well_name: str
    licence_number: str
    licensee_id: str
    licensee_name: str
    linked_facility_id: str
    linked_start_date: date | None
    field_code: str
    field_name: str
    area_name: str
    pool_code: str
    pool_name: str
    status_fluid: str
    status_mode: str
    status_type: str
    status_date: date | None
    spud_date: date | None
    drill_direction: str  # VERTICAL, HORIZONTAL, DIRECTIONAL, SLANT or ""
    total_depth_m: Decimal | None
    confidential_type: str
    licence_status: str
    is_orphan: bool
    is_masked: bool  # True if pool fields were "***" (confidential)


def format_uwi(identifier: str) -> str:
    """Format a 16-character Alberta well identifier as a UWI.

    "100010206504W400" -> "100/01-02-065-04W4/00"
    (location exception / LSD-section-township-range meridian / event sequence)
    """
    if len(identifier) != 16:
        raise ValueError(f"well identifier must be 16 characters: {identifier!r}")
    s = identifier
    return f"{s[0:3]}/{s[3:5]}-{s[5:7]}-{s[7:10]}-{s[10:12]}{s[12:14]}/{s[14:16]}"


def _text(value: str) -> str:
    value = value.strip()
    return "" if value == MASK else value


def _upper(value: str) -> str:
    """Normalize codes that Petrinex publishes in mixed case ("Vertical")."""
    return _text(value).upper()


def parse_well(raw: RawRow) -> WellRow:
    return WellRow(
        well_id=_text(raw["WellID"]),
        uwi=format_uwi(raw["WellIdentifier"].strip()),
        well_name=_text(raw["WellName"]),
        licence_number=_text(raw["LicenceNumber"]),
        licensee_id=_text(raw["LicenseeID"]),
        licensee_name=_text(raw["LicenseeName"]),
        linked_facility_id=_text(raw["LinkedFacilityID"]),
        linked_start_date=parse_date(raw["LinkedStartDate"]),
        field_code=_text(raw["Field"]),
        field_name=_text(raw["FieldName"]),
        area_name=_text(raw["AreaName"]),
        pool_code=_text(raw["PoolDeposit"]),
        pool_name=_text(raw["PoolDepositName"]),
        status_fluid=_upper(raw["WellStatusFluid"]),
        status_mode=_upper(raw["WellStatusMode"]),
        status_type=_upper(raw["WellStatusType"]),
        status_date=parse_date(raw["WellStatusDate"]),
        spud_date=parse_date(raw["SpudDate"]),
        drill_direction=_upper(raw["HorizontalDrill"]),
        total_depth_m=parse_decimal(raw["FinalTotalDepth"]),
        confidential_type=_upper(raw["ConfidentialType"]),
        licence_status=_upper(raw["LicenceStatus"]),
        is_orphan=raw["OrphanWellFlg"].strip().upper() == "Y",
        is_masked=any(raw[c].strip() == MASK for c in MASKABLE_COLUMNS),
    )


def iter_wells(zip_path: Path) -> Iterator[WellRow]:
    """Yield typed rows from a Well Infrastructure zip (streamed, ~680k rows)."""
    for line_num, raw in iter_raw_rows(zip_path, REQUIRED_COLUMNS):
        try:
            row = parse_well(raw)
        except ValueError as exc:
            raise ValueError(f"{zip_path.name} line {line_num}: {exc}") from exc
        yield row
