import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_custom_user_model_is_active() -> None:
    assert get_user_model() is User


def test_new_user_defaults_to_field_engineer() -> None:
    user = User.objects.create_user(username="sam", password="pw-123456")

    assert user.role == User.Role.FIELD_ENGINEER
    assert str(user) == "sam (field_engineer)"


def test_role_must_be_a_known_value() -> None:
    user = User(username="kim", role="ceo")

    with pytest.raises(ValidationError, match="role"):
        user.full_clean()
