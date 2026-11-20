from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import Client

from apps.documents.models import Document
from apps.users.models import User
from tests.helpers import pdf_bytes

pytestmark = pytest.mark.django_db

ADD_URL = "/admin/documents/document/add/"


# --- add_document command ---------------------------------------------------


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "directive060.pdf"
    path.write_bytes(pdf_bytes("d060"))
    return path


def add(path: Path, *extra: str) -> str:
    out = StringIO()
    call_command(
        "add_document",
        str(path),
        "--title",
        "Upstream Petroleum Industry Flaring, Incinerating, and Venting",
        "--kind",
        "regulation",
        "--roles",
        "field_engineer",
        "ops_manager",
        *extra,
        stdout=out,
    )
    return out.getvalue()


def test_command_adds_document(pdf_path: Path) -> None:
    output = add(pdf_path, "--reference", "Directive 060")

    document = Document.objects.get()
    assert document.reference == "Directive 060"
    assert document.allowed_roles == ["field_engineer", "ops_manager"]
    assert document.original_filename == "directive060.pdf"
    assert f"Added document {document.pk}: Directive 060" in output


def test_command_rejects_duplicate(pdf_path: Path) -> None:
    add(pdf_path)

    with pytest.raises(CommandError, match="already uploaded") as exc:
        add(pdf_path)
    assert "Sha256" not in str(exc.value)  # one clear message, not two
    assert Document.objects.count() == 1


def test_command_rejects_non_pdf(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    path.write_text("plain text")

    with pytest.raises(CommandError, match="not a PDF"):
        add(path)


def test_command_fails_without_file(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="not found"):
        add(tmp_path / "missing.pdf")


# --- admin upload -----------------------------------------------------------


def form_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": "Well work procedure",
        "kind": "procedure",
        "publisher": "",
        "reference": "",
        "edition": "",
        "source_url": "",
        "allowed_roles": ["ops_manager", "admin"],
        "file": SimpleUploadedFile("sop.pdf", pdf_bytes("sop")),
    }
    data.update(overrides)
    return data


def test_admin_uploads_document(client: Client) -> None:
    admin_user = User.objects.create_superuser("root", password="pw", role="admin")
    client.force_login(admin_user)

    response = client.post(ADD_URL, form_data())

    assert response.status_code == 302
    document = Document.objects.get()
    assert document.allowed_roles == ["ops_manager", "admin"]
    assert document.uploaded_by == admin_user


def test_admin_shows_error_for_non_pdf(client: Client) -> None:
    client.force_login(User.objects.create_superuser("root", password="pw"))

    response = client.post(
        ADD_URL, form_data(file=SimpleUploadedFile("sop.pdf", b"not a pdf"))
    )

    assert response.status_code == 200
    assert "The file is not a PDF." in response.content.decode()
    assert not Document.objects.exists()


def test_admin_requires_staff(client: Client) -> None:
    client.force_login(User.objects.create_user("engineer", password="pw"))

    response = client.post(ADD_URL, form_data())

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
    assert not Document.objects.exists()
