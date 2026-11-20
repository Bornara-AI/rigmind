from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File

PDF_MAGIC = b"%PDF-"


def validate_pdf(file: File) -> None:
    """Accept only PDFs within the size limit, checked by content, not just name."""
    max_mb: int = settings.DOCUMENT_MAX_UPLOAD_MB
    if file.size > max_mb * 1024 * 1024:
        raise ValidationError(f"File is larger than {max_mb} MB.", code="too_large")
    if not file.name.lower().endswith(".pdf"):
        raise ValidationError("Only .pdf files are accepted.", code="not_pdf")
    file.seek(0)
    header = file.read(len(PDF_MAGIC))
    file.seek(0)
    if header != PDF_MAGIC:
        raise ValidationError("The file is not a PDF.", code="not_pdf")
