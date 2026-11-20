import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from petrinex.download import (
    CODE_FILES,
    code_url,
    download,
    fetch,
    infra_filename,
    infra_url,
    main,
    month_range,
    sha256_file,
    vol_url,
)

Handler = Callable[[httpx.Request], httpx.Response]


class FakeSleep:
    """Records requested delays instead of sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def responses(*statuses: int, body: bytes = b"data") -> tuple[Handler, list[str]]:
    """Handler that returns the given statuses in order and records each URL."""
    calls: list[str] = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(queue.pop(0), content=body)

    return handler, calls


# --- month_range ------------------------------------------------------------


def test_month_range_crosses_year_boundary() -> None:
    assert month_range("2025-11", "2026-02") == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]


def test_month_range_single_month() -> None:
    assert month_range("2026-08", "2026-08") == ["2026-08"]


@pytest.mark.parametrize(
    ("start", "end"),
    [("2026-03", "2026-01"), ("26-01", "2026-02"), ("2026-13", "2027-01"), ("", "")],
)
def test_month_range_rejects_invalid_input(start: str, end: str) -> None:
    with pytest.raises(ValueError):
        month_range(start, end)


# --- URLs and file names ----------------------------------------------------


def test_vol_url() -> None:
    assert vol_url("2026-08") == (
        "https://www.petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/2026-08/CSV"
    )


def test_infra_url_encodes_spaces() -> None:
    assert infra_url("Well Infrastructure") == (
        "https://www.petrinex.gov.ab.ca/publicdata/API/Files/AB/Infra/"
        "Well%20Infrastructure/CSV"
    )


def test_code_url() -> None:
    assert code_url("PRAActivityCodes.csv") == (
        "https://www.petrinex.gov.ab.ca/bbreports/PRAActivityCodes.csv"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Well Infrastructure", "well-infrastructure.zip"),
        ("Well to Facility Link", "well-to-facility-link.zip"),
    ],
)
def test_infra_filename(name: str, expected: str) -> None:
    assert infra_filename(name) == expected


# --- sha256_file ------------------------------------------------------------


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "abc.txt"
    path.write_bytes(b"abc")

    assert sha256_file(path) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


# --- download ---------------------------------------------------------------


def test_download_writes_file_and_returns_size(tmp_path: Path) -> None:
    body = b"x" * 100_000
    handler, _ = responses(200, body=body)
    path = tmp_path / "file.zip"

    size = download(make_client(handler), "https://example.test/f", path)

    assert size == len(body)
    assert path.read_bytes() == body
    assert not path.with_name("file.zip.part").exists()


def test_download_retries_server_errors_with_backoff(tmp_path: Path) -> None:
    handler, calls = responses(503, 500, 200)
    sleep = FakeSleep()

    download(
        make_client(handler),
        "https://example.test/f",
        tmp_path / "f.zip",
        backoff=1.0,
        sleep=sleep,
    )

    assert len(calls) == 3
    assert sleep.delays == [1.0, 2.0]


def test_download_retries_network_errors(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, content=b"ok")

    sleep = FakeSleep()
    path = tmp_path / "f.zip"

    download(make_client(handler), "https://example.test/f", path, sleep=sleep)

    assert path.read_bytes() == b"ok"
    assert sleep.delays == [1.0]


def test_download_does_not_retry_404(tmp_path: Path) -> None:
    handler, calls = responses(404)
    sleep = FakeSleep()

    with pytest.raises(httpx.HTTPStatusError):
        download(
            make_client(handler),
            "https://example.test/f",
            tmp_path / "f.zip",
            sleep=sleep,
        )

    assert len(calls) == 1
    assert sleep.delays == []


def test_download_gives_up_after_attempts_and_leaves_no_files(tmp_path: Path) -> None:
    handler, calls = responses(503, 503, 503)
    sleep = FakeSleep()
    path = tmp_path / "f.zip"

    with pytest.raises(httpx.HTTPStatusError):
        download(
            make_client(handler),
            "https://example.test/f",
            path,
            attempts=3,
            sleep=sleep,
        )

    assert len(calls) == 3
    assert sleep.delays == [1.0, 2.0]
    assert not path.exists()
    assert not path.with_name("f.zip.part").exists()


# --- fetch ------------------------------------------------------------------


def read_manifest(dest: Path) -> list[dict[str, object]]:
    lines = (dest / "manifest.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_fetch_downloads_creates_folders_and_writes_manifest(tmp_path: Path) -> None:
    handler, _ = responses(200, body=b"abc")

    status = fetch(
        make_client(handler), "https://example.test/f", tmp_path, "vol/x.zip"
    )

    assert status == "downloaded"
    assert (tmp_path / "vol" / "x.zip").read_bytes() == b"abc"
    [record] = read_manifest(tmp_path)
    assert record["url"] == "https://example.test/f"
    assert record["path"] == "vol/x.zip"
    assert record["bytes"] == 3
    assert record["sha256"] == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert isinstance(record["downloaded_at"], str)


def test_fetch_skips_existing_file(tmp_path: Path) -> None:
    (tmp_path / "vol").mkdir()
    (tmp_path / "vol" / "x.zip").write_bytes(b"old")
    handler, calls = responses()

    status = fetch(
        make_client(handler), "https://example.test/f", tmp_path, "vol/x.zip"
    )

    assert status == "skipped"
    assert calls == []
    assert not (tmp_path / "manifest.jsonl").exists()


def test_fetch_force_replaces_existing_file(tmp_path: Path) -> None:
    (tmp_path / "vol").mkdir()
    (tmp_path / "vol" / "x.zip").write_bytes(b"old")
    handler, _ = responses(200, body=b"new")

    status = fetch(
        make_client(handler),
        "https://example.test/f",
        tmp_path,
        "vol/x.zip",
        force=True,
    )

    assert status == "downloaded"
    assert (tmp_path / "vol" / "x.zip").read_bytes() == b"new"
    assert len(read_manifest(tmp_path)) == 1


# --- main (CLI) -------------------------------------------------------------


def test_main_vol_downloads_each_month(tmp_path: Path) -> None:
    handler, calls = responses(200, 200)

    code = main(
        ["vol", "--from", "2026-07", "--to", "2026-08", "--dest", str(tmp_path)],
        client=make_client(handler),
    )

    assert code == 0
    assert calls == [vol_url("2026-07"), vol_url("2026-08")]
    assert (tmp_path / "vol" / "2026-07.zip").exists()
    assert (tmp_path / "vol" / "2026-08.zip").exists()


def test_main_infra_uses_slug_file_names(tmp_path: Path) -> None:
    handler, calls = responses(200)

    code = main(
        ["infra", "Well Infrastructure", "--dest", str(tmp_path)],
        client=make_client(handler),
    )

    assert code == 0
    assert calls == [infra_url("Well Infrastructure")]
    assert (tmp_path / "infra" / "well-infrastructure.zip").exists()


def test_main_codes_downloads_all_code_files(tmp_path: Path) -> None:
    handler, calls = responses(*[200] * len(CODE_FILES))

    code = main(["codes", "--dest", str(tmp_path)], client=make_client(handler))

    assert code == 0
    assert len(calls) == len(CODE_FILES)
    for name in CODE_FILES:
        assert (tmp_path / "codes" / name).exists()


def test_main_continues_after_a_failure_and_returns_1(tmp_path: Path) -> None:
    handler, calls = responses(404, 200)

    code = main(
        ["vol", "--from", "2026-07", "--to", "2026-08", "--dest", str(tmp_path)],
        client=make_client(handler),
    )

    assert code == 1
    assert len(calls) == 2
    assert not (tmp_path / "vol" / "2026-07.zip").exists()
    assert (tmp_path / "vol" / "2026-08.zip").exists()
