from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.documents.models import Document
from apps.users.models import User


class Command(BaseCommand):
    help = "Add a PDF to the document library with the roles that may read it."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", type=Path, help="PDF file to add")
        parser.add_argument("--title", required=True)
        parser.add_argument("--kind", required=True, choices=Document.Kind.values)
        parser.add_argument(
            "--roles",
            required=True,
            nargs="+",
            choices=User.Role.values,
            help="roles that may read the document",
        )
        parser.add_argument("--publisher", default="")
        parser.add_argument("--reference", default="", help='e.g. "Directive 060"')
        parser.add_argument("--edition", default="")
        parser.add_argument("--source-url", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["path"]
        if not path.is_file():
            raise CommandError(f"{path}: not found")

        with path.open("rb") as fh:
            document = Document(
                file=File(fh, name=path.name),
                title=options["title"],
                kind=options["kind"],
                allowed_roles=options["roles"],
                publisher=options["publisher"],
                reference=options["reference"],
                edition=options["edition"],
                source_url=options["source_url"],
            )
            try:
                document.full_clean()
            except ValidationError as exc:
                raise CommandError(f"{path}: {' '.join(exc.messages)}") from exc
            document.save()

        self.stdout.write(
            f"Added document {document.pk}: {document} "
            f"({document.size_bytes:,} bytes, sha256 {document.sha256[:12]})"
        )
