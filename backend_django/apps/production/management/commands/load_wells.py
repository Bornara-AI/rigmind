from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.production.loading import load_wells_file, unmatched_production_wells

DEFAULT_RELPATH = "infra/well-infrastructure.zip"
SHOW_UNMATCHED = 20


class Command(BaseCommand):
    help = (
        "Upsert wells from the Petrinex Well Infrastructure file, then report "
        "production wells that have no well record."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dest",
            type=Path,
            default=settings.PETRINEX_RAW_DIR,
            help=f"folder with {DEFAULT_RELPATH} (default: PETRINEX_RAW_DIR)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path = options["dest"] / DEFAULT_RELPATH
        if not path.exists():
            raise CommandError(
                f"{DEFAULT_RELPATH}: not found "
                '(run: python -m petrinex.download infra "Well Infrastructure")'
            )
        try:
            result = load_wells_file(path, source_file=DEFAULT_RELPATH)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"{DEFAULT_RELPATH}: {result.rows_staged:,} rows staged, "
            f"{result.wells:,} wells upserted"
        )

        unmatched = unmatched_production_wells()
        if not unmatched:
            self.stdout.write("All production wells have a well record.")
            return
        shown = ", ".join(unmatched[:SHOW_UNMATCHED])
        more = (
            f" (+{len(unmatched) - SHOW_UNMATCHED} more)"
            if len(unmatched) > SHOW_UNMATCHED
            else ""
        )
        self.stdout.write(
            f"{len(unmatched):,} production wells have no well record: {shown}{more}"
        )
