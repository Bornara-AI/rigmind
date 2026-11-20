import hashlib
from collections.abc import Collection
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models
from django.db.models import Q

from apps.documents.validators import validate_pdf
from apps.users.models import User


def sha256_of(file: File) -> str:
    digest = hashlib.sha256()
    for chunk in file.chunks():  # streams; never the whole file in memory
        digest.update(chunk)
    file.seek(0)
    return digest.hexdigest()


def document_upload_path(instance: "Document", filename: str) -> str:
    """Content-addressed path: the same bytes always land in the same place."""
    return f"documents/{instance.sha256[:2]}/{instance.sha256}.pdf"


class DocumentQuerySet(models.QuerySet["Document"]):
    def visible_to(self, role: str) -> "DocumentQuerySet":
        """Documents a user with this role may read. The AI service applies the
        same rule in SQL (allowed_roles @> ARRAY[role]) before retrieval."""
        return self.filter(allowed_roles__contains=[role])


class Document(models.Model):
    """A PDF (regulation or internal document) that answers can cite."""

    class Kind(models.TextChoices):
        REGULATION = "regulation", "Regulation"
        PROCEDURE = "procedure", "Procedure"
        REPORT = "report", "Report"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=300)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    publisher = models.CharField(
        max_length=200, blank=True, help_text="e.g. Alberta Energy Regulator"
    )
    reference = models.CharField(
        max_length=100, blank=True, help_text='Short citation label: "Directive 060"'
    )
    edition = models.CharField(
        max_length=100, blank=True, help_text="Edition or release date as printed"
    )
    source_url = models.URLField(max_length=500, blank=True)
    allowed_roles = ArrayField(
        models.CharField(max_length=32, choices=User.Role.choices),
        help_text="Roles that may read this document and see its passages.",
    )
    file = models.FileField(upload_to=document_upload_path, validators=[validate_pdf])
    original_filename = models.CharField(max_length=255, editable=False)
    sha256 = models.CharField(max_length=64, unique=True, editable=False)
    size_bytes = models.PositiveBigIntegerField(editable=False)
    page_count = models.PositiveIntegerField(null=True, blank=True, editable=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPLOADED
    )
    status_detail = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        db_table = "documents"
        ordering = ["title"]
        constraints = [
            models.CheckConstraint(
                condition=Q(allowed_roles__len__gt=0)
                & Q(allowed_roles__contained_by=User.Role.values),
                name="documents_allowed_roles_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference}: {self.title}" if self.reference else self.title

    def save(self, *args: Any, **kwargs: Any) -> None:
        self._read_file_metadata()  # also when saved without full_clean()
        super().save(*args, **kwargs)

    def _read_file_metadata(self) -> None:
        if self.sha256 or not self.file:
            return
        self.sha256 = sha256_of(self.file)
        self.size_bytes = self.file.size
        self.original_filename = Path(self.file.name).name

    def clean(self) -> None:
        self._read_file_metadata()
        if not self.sha256:
            return
        duplicate = Document.objects.filter(sha256=self.sha256).exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError(
                {"file": f'This file was already uploaded as "{duplicate.get()}".'}
            )

    def validate_unique(self, exclude: Collection[str] | None = None) -> None:
        # clean() reports a duplicate file in words a user understands.
        super().validate_unique(exclude={*(exclude or ()), "sha256"})
