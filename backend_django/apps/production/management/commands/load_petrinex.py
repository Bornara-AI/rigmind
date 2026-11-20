from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.production.loading import analyze_production_tables, load_volumetric_file
from petrinex.download import month_range


class Command(BaseCommand):
    help = (
        "Load downloaded Petrinex volumetrics into the production tables. "
        "Each month is replaced in its own transaction; files identical to the "
        "last load of their month are skipped unless --force is given."
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
        parser.add_argument(
            "--force", action="store_true", help="reload even if the file is unchanged"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        months = self._months(options["month"], options["start"], options["end"])
        dest: Path = options["dest"]

        failed: list[str] = []
        loaded = 0
        for month in months:
            relpath = f"vol/{month}.zip"
            path = dest / relpath
            if not path.exists():
                self.stderr.write(f"{relpath}: not found (run petrinex.download)")
                failed.append(month)
                continue
            try:
                result = load_volumetric_file(
                    path, month, source_file=relpath, force=options["force"]
                )
            except ValueError as exc:
                self.stderr.write(f"{relpath}: {exc}")
                failed.append(month)
                continue
            if result.skipped:
                self.stdout.write(f"{month}: unchanged since the last load, skipped")
                continue
            loaded += 1
            self.stdout.write(
                f"{month}: {result.rows_staged:,} rows staged, "
                f"{result.production_rows:,} production, "
                f"{result.activity_rows:,} flare/vent/fuel"
            )

        if loaded:
            analyze_production_tables()

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
