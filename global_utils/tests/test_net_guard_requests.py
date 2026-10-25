import pytest
import requests

from global_utils.utils.net_guard import UnsafeUrlError
from global_utils.utils.net_guard_requests import GuardedAdapter


def test_every_request_of_a_session_is_vetted_before_sending(monkeypatch):
    sent = []
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", lambda self, request, **kw: sent.append(request.url) or requests.Response())
    adapter = GuardedAdapter(resolver=lambda host: {"ok.example.com": ["93.184.216.34"], "bad.example.com": ["169.254.169.254"]}[host])
    session = requests.Session()
    session.mount("https://", adapter)
    session.get("https://ok.example.com/a")
    with pytest.raises(UnsafeUrlError):
        session.get("https://bad.example.com/b")
    assert sent == ["https://ok.example.com/a"]
