"""Stream rows from Petrinex Conventional Volumetrics files.

The download is a zip that contains another zip that contains one CSV
(~120 MB, ~530k rows per month). Rows are streamed straight from the inner zip:
nothing is extracted to disk and the whole file is never held as text.
"""

import csv
import io
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

MASK = "***"
WELL = "WI"
PRODUCTION = "PROD"
EMISSION_ACTIVITIES = frozenset({"FLARE", "VENT", "FUEL"})
MASKABLE_COLUMNS = ("FromToID", "Volume", "Energy", "Hours")
REQUIRED_COLUMNS = frozenset(
    {
        "ProductionMonth",
        "OperatorBAID",
        "OperatorName",
        "ReportingFacilityID",
        "ReportingFacilityType",
        "ReportingFacilityName",
        "ReportingFacilitySubType",
        "SubmissionDate",
        "ActivityID",
        "ProductID",
        "FromToID",
        "FromToIDType",
        "Volume",
        "Energy",
        "Hours",
    }
)

RawRow = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class VolumetricRow:
    """One volumetric record. IDs stay text; masked or blank values are None."""

    production_month: str  # "YYYY-MM"
    operator_baid: str
    operator_name: str
    reporting_facility_id: str
    reporting_facility_type: str
    reporting_facility_name: str
    reporting_facility_subtype: str
    submission_date: date | None
    activity_id: str
    product_id: str
    from_to_id: str | None
    from_to_id_type: str | None
    volume: Decimal | None  # m3 for liquids, e3m3 for gas
    energy: Decimal | None  # GJ
    hours: int | None
    is_masked: bool  # True if any of MASKABLE_COLUMNS was "***" in the source


def is_relevant(raw: RawRow) -> bool:
    """Keep well production rows and all flare / vent / fuel rows."""
    activity = raw["ActivityID"]
    if activity == PRODUCTION:
        return raw["FromToIDType"] == WELL
    return activity in EMISSION_ACTIVITIES


def clean_text(value: str) -> str | None:
    value = value.strip()
    return None if value in ("", MASK) else value


def parse_decimal(value: str) -> Decimal | None:
    text = clean_text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}") from None


def parse_int(value: str) -> int | None:
    text = clean_text(value)
    return None if text is None else int(text)


def parse_date(value: str) -> date | None:
    text = clean_text(value)
    return None if text is None else date.fromisoformat(text)


def parse_row(raw: RawRow) -> VolumetricRow:
    """Convert one CSV row (column name -> text) into a typed VolumetricRow."""
    return VolumetricRow(
        production_month=raw["ProductionMonth"].strip(),
        operator_baid=raw["OperatorBAID"].strip(),
        operator_name=raw["OperatorName"].strip(),
        reporting_facility_id=raw["ReportingFacilityID"].strip(),
        reporting_facility_type=raw["ReportingFacilityType"].strip(),
        reporting_facility_name=raw["ReportingFacilityName"].strip(),
        reporting_facility_subtype=raw["ReportingFacilitySubType"].strip(),
        submission_date=parse_date(raw["SubmissionDate"]),
        activity_id=raw["ActivityID"].strip(),
        product_id=raw["ProductID"].strip(),
        from_to_id=clean_text(raw["FromToID"]),
        from_to_id_type=clean_text(raw["FromToIDType"]),
        volume=parse_decimal(raw["Volume"]),
        energy=parse_decimal(raw["Energy"]),
        hours=parse_int(raw["Hours"]),
        is_masked=any(raw[column].strip() == MASK for column in MASKABLE_COLUMNS),
    )


def _single_member(archive: zipfile.ZipFile, suffix: str) -> str:
    names = [n for n in archive.namelist() if n.lower().endswith(suffix)]
    if len(names) != 1:
        raise ValueError(f"expected one {suffix} file, found {names}")
    return names[0]


@contextmanager
def open_csv(zip_path: Path) -> Iterator[TextIO]:
    """Open the CSV inside a Petrinex zip (zip-in-zip or a plain zip) as text."""
    with zipfile.ZipFile(zip_path) as outer:
        if any(n.lower().endswith(".zip") for n in outer.namelist()):
            # The inner zip is small (~8 MB compressed): hold it in memory and
            # stream-decompress the CSV from it.
            inner_bytes = outer.read(_single_member(outer, ".zip"))
            archive = zipfile.ZipFile(io.BytesIO(inner_bytes))
        else:
            archive = outer
        with archive, archive.open(_single_member(archive, ".csv")) as raw:
            yield io.TextIOWrapper(raw, encoding="utf-8", newline="")


def iter_raw_rows(
    zip_path: Path, required: frozenset[str]
) -> Iterator[tuple[int, RawRow]]:
    """Yield (line number, row) from the CSV in zip_path after checking the header."""
    with open_csv(zip_path) as text:
        reader = csv.DictReader(text)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{zip_path.name}: missing columns {sorted(missing)}")
        for raw in reader:
            yield reader.line_num, raw


def iter_rows(
    zip_path: Path,
    *,
    keep: Callable[[RawRow], bool] | None = is_relevant,
) -> Iterator[VolumetricRow]:
    """Yield typed rows from a volumetrics zip, filtered by `keep` before parsing.

    Pass keep=None to get every row. Raises ValueError if required columns are
    missing or a value cannot be parsed (the message names the file and line).
    """
    for line_num, raw in iter_raw_rows(zip_path, REQUIRED_COLUMNS):
        if keep is not None and not keep(raw):
            continue
        try:
            row = parse_row(raw)
        except ValueError as exc:
            raise ValueError(f"{zip_path.name} line {line_num}: {exc}") from exc
        yield row
