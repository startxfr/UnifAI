"""The content-duplicate check only matches documents of the same uploader."""
from unittest.mock import MagicMock

from infrastructure.sources.document.validator.duplicate_checker import DocumentDuplicateCheckerAdapter as DuplicateChecker


def _checker(sources):
    storage = MagicMock()
    storage.get_source_by_query.return_value = sources
    storage.get_pipeline_status.return_value = "DONE"
    return DuplicateChecker(storage), storage


def test_the_query_is_limited_to_the_uploader():
    checker, storage = _checker([{"pipeline_id": "p1"}])
    assert checker.is_duplicate({"md5": "abc", "upload_by": "alice"})
    query = storage.get_source_by_query.call_args.args[0]
    assert query["type_data.md5"] == "abc" and query["upload_by"] == "alice"


def test_another_users_identical_file_is_not_reported():
    checker, storage = _checker([])  # the store holds a file with this md5, but not alice's
    assert not checker.is_duplicate({"md5": "abc", "upload_by": "alice"})
    assert storage.get_source_by_query.call_args.args[0]["upload_by"] == "alice"
