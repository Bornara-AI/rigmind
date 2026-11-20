from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.documents.models import Document
from apps.users.models import User


class DocumentForm(forms.ModelForm):
    allowed_roles = forms.MultipleChoiceField(
        choices=User.Role.choices, widget=forms.CheckboxSelectMultiple
    )
    source_url = forms.URLField(max_length=500, required=False, assume_scheme="https")

    class Meta:
        model = Document
        fields = [
            "title",
            "kind",
            "publisher",
            "reference",
            "edition",
            "source_url",
            "allowed_roles",
            "file",
        ]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    form = DocumentForm
    list_display = ("title", "reference", "kind", "roles", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("title", "reference", "sha256")
    readonly_fields = (
        "original_filename",
        "sha256",
        "size_bytes",
        "page_count",
        "status",
        "status_detail",
        "uploaded_by",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Allowed roles")
    def roles(self, obj: Document) -> str:
        return ", ".join(obj.allowed_roles)

    def get_readonly_fields(
        self, request: HttpRequest, obj: Document | None = None
    ) -> tuple[str, ...]:
        fields = tuple(super().get_readonly_fields(request, obj))
        # The file is fixed once uploaded: a new edition is a new document.
        return (*fields, "file") if obj else fields

    def save_model(
        self, request: HttpRequest, obj: Document, form: Any, change: bool
    ) -> None:
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
