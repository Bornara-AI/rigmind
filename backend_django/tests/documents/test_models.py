import hashlib
from collections.abc import Callable
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError

from apps.documents.models import Document
from apps.documents.validators import validate_pdf
from tests.helpers import pdf_bytes

pytestmark = pytest.mark.django_db

MakeDocument = Callable[..., Document]


def test_save_records_hash_size_and_stores_by_content(
    make_document: MakeDocument,
) -> None:
    document = make_document("d060")

    digest = hashlib.sha256(pdf_bytes("d060")).hexdigest()
    assert document.sha256 == digest
    assert document.size_bytes == len(pdf_bytes("d060"))
    assert document.original_filename == "d060.pdf"
    assert document.file.name == f"documents/{digest[:2]}/{digest}.pdf"
    assert document.file.storage.exists(document.file.name)
    assert document.status == Document.Status.UPLOADED


def test_same_file_twice_is_rejected(make_document: MakeDocument) -> None:
    make_document("d060", reference="Directive 060")

    with pytest.raises(ValidationError) as exc:
        make_document("d060", title="Copy")

    assert "already uploaded" in str(exc.value.message_dict["file"])


def test_visible_to_filters_by_role(make_document: MakeDocument) -> None:
    public = make_document("public")
    managers = make_document("managers", allowed_roles=["ops_manager", "admin"])

    assert list(Document.objects.visible_to("field_engineer")) == [public]
    assert set(Document.objects.visible_to("ops_manager")) == {public, managers}


@pytest.mark.parametrize("roles", [["guest"], []])
def test_clean_rejects_invalid_roles(
    make_document: MakeDocument, roles: list[str]
) -> None:
    with pytest.raises(ValidationError) as exc:
        make_document(allowed_roles=roles)

    assert "allowed_roles" in exc.value.message_dict


@pytest.mark.parametrize("roles", [["guest"], []])
def test_database_rejects_invalid_roles(roles: list[str]) -> None:
    upload = SimpleUploadedFile("x.pdf", pdf_bytes("x"))
    with pytest.raises(IntegrityError, match="documents_allowed_roles_valid"):
        Document.objects.create(
            file=upload, title="x", kind="regulation", allowed_roles=roles
        )


# --- validate_pdf -----------------------------------------------------------


def test_validate_pdf_accepts_pdf() -> None:
    validate_pdf(SimpleUploadedFile("a.pdf", pdf_bytes()))


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("a.txt", pdf_bytes(), "Only .pdf"),
        ("a.pdf", b"MZ\x90\x00 not a pdf", "not a PDF"),
    ],
)
def test_validate_pdf_rejects_other_files(
    name: str, content: bytes, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        validate_pdf(SimpleUploadedFile(name, content))


def test_validate_pdf_rejects_large_files(settings: Any) -> None:
    settings.DOCUMENT_MAX_UPLOAD_MB = 0

    with pytest.raises(ValidationError, match="larger than 0 MB"):
        validate_pdf(SimpleUploadedFile("a.pdf", pdf_bytes()))
