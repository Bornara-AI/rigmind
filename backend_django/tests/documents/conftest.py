from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import Document
from tests.helpers import pdf_bytes

ALL_ROLES = ["field_engineer", "ops_manager", "admin"]


@pytest.fixture(autouse=True)
def media_root(settings: Any, tmp_path: Path) -> Path:
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def make_document(db: None) -> Callable[..., Document]:
    def make(text: str = "sample", **fields: Any) -> Document:
        fields.setdefault("title", f"Document {text}")
        fields.setdefault("kind", Document.Kind.REGULATION)
        fields.setdefault("allowed_roles", ALL_ROLES)
        upload = SimpleUploadedFile(f"{text}.pdf", pdf_bytes(text))
        document = Document(file=upload, **fields)
        document.full_clean()
        document.save()
        return document

    return make
