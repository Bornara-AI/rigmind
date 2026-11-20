"""Shared test helpers for Petrinex files."""

import csv
import io
import zipfile
from pathlib import Path

VOL_FIXTURE = Path(__file__).parent / "fixtures" / "petrinex" / "vol_2026-08_sample.csv"


def nested_zip(csv_bytes: bytes, folder: Path, name: str = "2026-08.zip") -> Path:
    """Package CSV bytes like the real download: a zip inside a zip."""
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Vol_2026-08-AB.CSV", csv_bytes)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Vol_2026-08-AB.csv.zip", inner.getvalue())
    return path


def fixture_rows() -> tuple[list[str], list[dict[str, str]]]:
    with VOL_FIXTURE.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def to_csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")
