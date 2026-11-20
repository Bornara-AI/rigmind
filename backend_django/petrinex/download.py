"""Download Petrinex Alberta public data files.

Usage:
    python -m petrinex.download vol --from 2024-09 --to 2026-08
    python -m petrinex.download infra "Well Infrastructure" "Well Licence"
    python -m petrinex.download codes

Files are saved under PETRINEX_RAW_DIR (default: data/raw/petrinex):
    vol/2026-08.zip, infra/well-infrastructure.zip, codes/PRAActivityCodes.csv
Every downloaded file is recorded in manifest.jsonl (url, path, bytes, sha256, time).
"""

import argparse
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.petrinex.gov.ab.ca"
DEFAULT_DEST = Path(os.environ.get("PETRINEX_RAW_DIR", "data/raw/petrinex"))
MANIFEST_NAME = "manifest.jsonl"
CODE_FILES = [
    "PRAActivityCodes.csv",
    "PRAFieldCodes.csv",
    "PRAFieldandPoolCodes.csv",
    "PRAFacilityCodes.csv",
    "PRABAIdentifiers.csv",
]
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
CHUNK_SIZE = 1024 * 1024  # 1 MiB

Sleep = Callable[[float], None]
FetchStatus = Literal["downloaded", "skipped"]

_MONTH_RE = re.compile(r"(\d{4})-(\d{2})")


def _parse_month(value: str) -> tuple[int, int]:
    """Parse "YYYY-MM" into (year, month), or raise ValueError."""
    match = _MONTH_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"Expected YYYY-MM, got {value!r}")
    year, month = int(match[1]), int(match[2])
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 01-12, got {value!r}")
    return year, month


def month_range(start: str, end: str) -> list[str]:
    """Return every month from start to end inclusive, as "YYYY-MM" strings.

    month_range("2025-11", "2026-02") -> ["2025-11", "2025-12", "2026-01", "2026-02"]
    Raises ValueError for a bad format ("26-01", "2026-13") or if start > end.
    """
    current, last = _parse_month(start), _parse_month(end)
    if current > last:
        raise ValueError(f"Start {start} is after end {end}")

    months: list[str] = []
    while current <= last:
        year, month = current
        months.append(f"{year:04d}-{month:02d}")
        current = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def vol_url(month: str) -> str:
    """URL of the Conventional Volumetrics zip for one month ("YYYY-MM")."""
    return f"{BASE_URL}/publicdata/API/Files/AB/Vol/{month}/CSV"


def infra_url(name: str) -> str:
    """URL of an infrastructure report, e.g. "Well Infrastructure" (spaces encoded)."""
    return f"{BASE_URL}/publicdata/API/Files/AB/Infra/{quote(name)}/CSV"


def code_url(filename: str) -> str:
    """URL of a code lookup CSV, e.g. "PRAActivityCodes.csv"."""
    return f"{BASE_URL}/bbreports/{filename}"


def infra_filename(name: str) -> str:
    """Local file name for a report: "Well Licence" -> "well-licence.zip"."""
    return "-".join(name.lower().split()) + ".zip"


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file, read in chunks (files can be hundreds of MB)."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_retryable(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in RETRYABLE_STATUS
    )


def download(
    client: httpx.Client,
    url: str,
    path: Path,
    *,
    attempts: int = 4,
    backoff: float = 1.0,
    sleep: Sleep = time.sleep,
) -> int:
    """Stream url to path and return the number of bytes written.

    - Writes to "<path>.part" first and renames it to path only on success,
      so a failed or interrupted download never leaves a half file at path.
    - Tries up to `attempts` times. Retries network errors (httpx.TransportError)
      and RETRYABLE_STATUS responses; after the n-th failed try it waits
      backoff * 2 ** (n - 1) seconds. Never sleeps after the last try.
    - Other HTTP errors (e.g. 404) are raised at once without retrying.
    """
    part = path.with_name(f"{path.name}.part")

    for attempt in range(1, attempts + 1):
        try:
            size = 0
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with part.open("wb") as f:
                    for chunk in response.iter_bytes(CHUNK_SIZE):
                        f.write(chunk)
                        size += len(chunk)
            part.replace(path)
            return size
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            part.unlink(missing_ok=True)
            if not _is_retryable(exc) or attempt == attempts:
                raise
            delay = backoff * 2 ** (attempt - 1)
            logger.warning(
                "Attempt %d/%d failed for %s (%s); retrying in %.0fs",
                attempt,
                attempts,
                url,
                exc,
                delay,
            )
            sleep(delay)

    raise ValueError("attempts must be at least 1")


def fetch(
    client: httpx.Client,
    url: str,
    dest: Path,
    relpath: str,
    *,
    force: bool = False,
    sleep: Sleep = time.sleep,
) -> FetchStatus:
    """Download url to dest/relpath unless it already exists (or force is True).

    Creates parent folders. After a download, appends one JSON line to
    dest/manifest.jsonl with keys: url, path (= relpath), bytes, sha256,
    downloaded_at (UTC ISO 8601). Skipped files are not added to the manifest.
    """
    path = dest / relpath
    if path.exists() and not force:
        logger.info("Skip %s (already downloaded)", relpath)
        return "skipped"

    path.parent.mkdir(parents=True, exist_ok=True)
    size = download(client, url, path, sleep=sleep)

    record = {
        "url": url,
        "path": relpath,
        "bytes": size,
        "sha256": sha256_file(path),
        "downloaded_at": datetime.now(UTC).isoformat(),
    }
    with (dest / MANIFEST_NAME).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    logger.info("Downloaded %s (%d bytes)", relpath, size)
    return "downloaded"


def build_client() -> httpx.Client:
    """HTTP client with timeouts sized for large files."""
    return httpx.Client(
        timeout=httpx.Timeout(30.0, read=120.0),
        follow_redirects=True,
        headers={"User-Agent": "rigmind-petrinex-downloader"},
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    common.add_argument("--force", action="store_true", help="re-download files")

    parser = argparse.ArgumentParser(
        prog="python -m petrinex.download", description=__doc__
    )
    sub = parser.add_subparsers(dest="kind", required=True)

    vol = sub.add_parser("vol", parents=[common], help="monthly volumetrics")
    vol.add_argument("--from", dest="start", required=True, metavar="YYYY-MM")
    vol.add_argument("--to", dest="end", required=True, metavar="YYYY-MM")

    infra = sub.add_parser("infra", parents=[common], help="infrastructure reports")
    infra.add_argument("names", nargs="+", metavar="NAME")

    sub.add_parser("codes", parents=[common], help="code lookup CSVs")
    return parser.parse_args(argv)


def _jobs(args: argparse.Namespace) -> list[tuple[str, str]]:
    """(url, relpath) pairs for the chosen subcommand."""
    if args.kind == "vol":
        return [(vol_url(m), f"vol/{m}.zip") for m in month_range(args.start, args.end)]
    if args.kind == "infra":
        return [(infra_url(n), f"infra/{infra_filename(n)}") for n in args.names]
    return [(code_url(name), f"codes/{name}") for name in CODE_FILES]


def main(argv: list[str] | None = None, *, client: httpx.Client | None = None) -> int:
    """CLI entry point. Returns the process exit code.

    Subcommands: vol (--from, --to), infra (one or more report names), codes.
    Common options: --dest (default DEFAULT_DEST), --force.
    Downloads one file at a time. If a file fails, log the error and continue
    with the rest; return 1 if anything failed, else 0.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    jobs = _jobs(args)

    failed: list[str] = []
    with client or build_client() as http:
        for url, relpath in jobs:
            try:
                fetch(http, url, args.dest, relpath, force=args.force)
            except httpx.HTTPError as exc:
                logger.error("Failed %s: %s", url, exc)
                failed.append(relpath)

    if failed:
        logger.error("%d of %d files failed: %s", len(failed), len(jobs), failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
