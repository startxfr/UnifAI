import pytest

from global_utils.utils.net_guard import UnsafeUrlError, check_outbound_url


def resolver_for(mapping):
    return lambda host: mapping[host]


PUBLIC = resolver_for({"mcp.example.com": ["93.184.216.34"], "rebind.example.com": ["93.184.216.34", "10.0.0.5"]})


def test_a_public_host_is_allowed():
    assert check_outbound_url("https://mcp.example.com/mcp", resolver=PUBLIC)


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:6379/",
    "http://localhost:8080/",
    "http://[::1]:8080/",
    "http://10.0.0.5/",
    "http://192.168.1.10/",
    "http://172.16.0.1/",
    "http://0.0.0.0/",
    "http://[::ffff:169.254.169.254]/",
    "http://100.64.0.1/",
])
def test_non_public_literals_are_refused(url):
    with pytest.raises(UnsafeUrlError):
        check_outbound_url(url, resolver=PUBLIC)


def test_a_name_resolving_to_a_private_address_is_refused_even_if_one_address_is_public():
    with pytest.raises(UnsafeUrlError):
        check_outbound_url("https://rebind.example.com/", resolver=PUBLIC)


@pytest.mark.parametrize("url", [
    "ftp://mcp.example.com/", "file:///etc/passwd", "gopher://mcp.example.com/", "https://", "not a url", "",
    "https://user:pw@mcp.example.com/",
])
def test_odd_urls_are_refused(url):
    with pytest.raises(UnsafeUrlError):
        check_outbound_url(url, resolver=PUBLIC)


@pytest.mark.parametrize("url", [
    "http://ai-gateway.zuno-ai-run.svc:8080/v1",
    "http://mcp-gateway.zuno-ai-run.svc.cluster.local:8080/mcp",
])
def test_the_platform_runtime_namespace_is_allowed_by_name(url):
    boom = lambda host: (_ for _ in ()).throw(AssertionError("must not resolve"))  # noqa: E731
    assert check_outbound_url(url, resolver=boom)


@pytest.mark.parametrize("url", [
    "http://unifai-mongo:27017/", "http://redis.zuno-unifai.svc:6379/", "http://zuno-ai-run.svc.evil.example/",
    "http://x.zuno-ai-run.svc.evil.example/",
])
def test_other_internal_names_are_refused(url):
    with pytest.raises(UnsafeUrlError):
        check_outbound_url(url, resolver=resolver_for({
            "unifai-mongo": ["10.1.2.3"], "redis.zuno-unifai.svc": ["10.1.2.4"],
            "zuno-ai-run.svc.evil.example": ["10.9.9.9"], "x.zuno-ai-run.svc.evil.example": ["10.9.9.9"],
        }))


def test_the_operator_can_allow_a_host_or_a_suffix(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOWED_HOSTS", "confluence.corp.internal, .tools.corp.internal")
    boom = lambda host: ["10.0.0.9"]  # noqa: E731
    assert check_outbound_url("https://confluence.corp.internal/wiki", resolver=boom)
    assert check_outbound_url("https://a.tools.corp.internal/", resolver=boom)
    with pytest.raises(UnsafeUrlError):
        check_outbound_url("https://other.corp.internal/", resolver=boom)


def test_an_unresolvable_host_is_refused():
    with pytest.raises(UnsafeUrlError):
        check_outbound_url("https://nowhere.example.com/", resolver=lambda host: [])


def test_the_resolver_lists_ipv4_addresses_before_ipv6(monkeypatch):
    import socket as _socket

    from global_utils.utils import net_guard

    infos = [(0, 0, 0, "", ("2606:4700::1", 0)), (0, 0, 0, "", ("93.184.216.34", 0)), (0, 0, 0, "", ("104.18.0.1", 0))]
    monkeypatch.setattr(_socket, "getaddrinfo", lambda *a, **k: infos)
    assert net_guard._resolve("example.com") == ["104.18.0.1", "93.184.216.34", "2606:4700::1"]
