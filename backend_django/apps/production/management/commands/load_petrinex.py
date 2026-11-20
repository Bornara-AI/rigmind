from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.production.loading import load_volumetric_file
from petrinex.download import month_range


class Command(BaseCommand):
    help = (
        "Load downloaded Petrinex volumetrics into the production tables. "
        "Each month is replaced in its own transaction."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--month", metavar="YYYY-MM", help="load one month")
        parser.add_argument("--from", dest="start", metavar="YYYY-MM")
        parser.add_argument("--to", dest="end", metavar="YYYY-MM")
        parser.add_argument(
            "--dest",
            type=Path,
            default=settings.PETRINEX_RAW_DIR,
            help="folder with vol/YYYY-MM.zip (default: PETRINEX_RAW_DIR)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        months = self._months(options["month"], options["start"], options["end"])
        dest: Path = options["dest"]

        failed: list[str] = []
        for month in months:
            relpath = f"vol/{month}.zip"
            path = dest / relpath
            if not path.exists():
                self.stderr.write(f"{relpath}: not found (run petrinex.download)")
                failed.append(month)
                continue
            try:
                result = load_volumetric_file(path, month, source_file=relpath)
            except ValueError as exc:
                self.stderr.write(f"{relpath}: {exc}")
                failed.append(month)
                continue
            self.stdout.write(
                f"{month}: {result.rows_staged:,} rows staged, "
                f"{result.production_rows:,} production, "
                f"{result.activity_rows:,} flare/vent/fuel"
            )

        if failed:
            raise CommandError(
                f"{len(failed)} of {len(months)} months failed: {failed}"
            )

    @staticmethod
    def _months(month: str | None, start: str | None, end: str | None) -> list[str]:
        try:
            if month and not (start or end):
                return month_range(month, month)
            if start and end and not month:
                return month_range(start, end)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        raise CommandError("use either --month YYYY-MM or --from YYYY-MM --to YYYY-MM")
