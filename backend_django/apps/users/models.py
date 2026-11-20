from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user. The role decides which documents and features they can use."""

    class Role(models.TextChoices):
        FIELD_ENGINEER = "field_engineer", "Field engineer"
        OPS_MANAGER = "ops_manager", "Operations manager"
        ADMIN = "admin", "Admin"

    role = models.CharField(
        max_length=32, choices=Role.choices, default=Role.FIELD_ENGINEER
    )

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"
