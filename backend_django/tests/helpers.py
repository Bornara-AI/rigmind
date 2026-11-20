"""Shared test helpers for Petrinex files."""

import csv
import io
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "petrinex"
VOL_FIXTURE = FIXTURES / "vol_2026-08_sample.csv"
WELLS_FIXTURE = FIXTURES / "well_infrastructure_sample.csv"


def nested_zip(
    csv_bytes: bytes,
    folder: Path,
    name: str = "2026-08.zip",
    inner_csv: str = "Vol_2026-08-AB.CSV",
) -> Path:
    """Package CSV bytes like the real download: a zip inside a zip."""
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(inner_csv, csv_bytes)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{inner_csv[:-4]}.csv.zip", inner.getvalue())
    return path


def wells_zip(folder: Path, csv_bytes: bytes | None = None) -> Path:
    """Well Infrastructure fixture packaged as infra/well-infrastructure.zip."""
    data = WELLS_FIXTURE.read_bytes() if csv_bytes is None else csv_bytes
    return nested_zip(
        data,
        folder / "infra",
        name="well-infrastructure.zip",
        inner_csv="Well Infrastructure-AB.CSV",
    )


def fixture_rows(
    path: Path = VOL_FIXTURE,
) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def to_csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def pdf_bytes(text: str = "sample") -> bytes:
    """Bytes that pass the PDF check; the text makes each file's hash unique."""
    return f"%PDF-1.4\n% {text}\n%%EOF\n".encode()
