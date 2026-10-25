"""A custom (non built-in) resource id answers like a missing one on the built-in endpoints' service calls."""
from unittest.mock import MagicMock

import pytest

from mas.core.identity import Identity
from mas.resources.builtin_service import BuiltinResourceService


@pytest.fixture
def service():
    descriptors = MagicMock()
    descriptors.get.return_value = None  # the id exists in the store but is nobody's built-in
    svc = BuiltinResourceService(MagicMock(), MagicMock(), MagicMock(), descriptors, MagicMock())
    svc.get_descriptor = MagicMock(return_value=None)
    return svc


def test_schema_of_a_non_builtin_looks_like_a_missing_resource(service):
    with pytest.raises(KeyError):
        service.get_builtin_schema("someone-elses-resource")


def test_user_config_of_a_non_builtin_looks_like_a_missing_resource(service):
    with pytest.raises(KeyError):
        service.get_user_config("someone-elses-resource", Identity.user("alice"))


def test_configure_of_a_non_builtin_looks_like_a_missing_resource(service):
    with pytest.raises(KeyError):
        service.configure_builtin("someone-elses-resource", Identity.user("alice"), {})
