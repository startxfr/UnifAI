"""The requests adapter pins the connection to the vetted address over a real socket, plain and TLS."""
import datetime
import ipaddress
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

pytest.importorskip("cryptography")
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from global_utils.utils import net_guard
from global_utils.utils.net_guard import UnsafeUrlError
from global_utils.utils.net_guard_requests import guard_session

NAME = "fixture.test"
seen_hosts: list = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        seen_hosts.append(self.headers.get("Host"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"pong")

    def log_message(self, *args):  # silence
        pass


def _certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(NAME)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(cert_path), str(key_path)


@pytest.fixture
def server(tmp_path):
    seen_hosts.clear()
    cert, key = _certificate(tmp_path)
    plain, tls = HTTPServer(("127.0.0.1", 0), Handler), HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    tls.socket = context.wrap_socket(tls.socket, server_side=True)
    for srv in (plain, tls):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield plain.server_port, tls.server_port, cert
    for srv in (plain, tls):
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def dns(monkeypatch):
    state = {"answer": "127.0.0.1"}
    real = net_guard._is_public
    monkeypatch.setattr(net_guard, "_resolve", lambda host: [state["answer"]] if host == NAME else [])
    monkeypatch.setattr(net_guard, "_is_public", lambda a: a == "127.0.0.1" or real(a))
    return state


def test_plain_http_connects_to_the_vetted_address_and_keeps_the_host_header(server, dns):
    plain, _, _ = server
    session = guard_session(requests.Session())
    assert session.get(f"http://{NAME}:{plain}/", timeout=5).text == "pong"
    assert seen_hosts == [f"{NAME}:{plain}"]


def test_tls_checks_the_certificate_against_the_original_name(server, dns):
    _, tls, cert = server
    session = guard_session(requests.Session())
    session.verify = cert
    assert session.get(f"https://{NAME}:{tls}/", timeout=5).text == "pong"
    assert seen_hosts == [f"{NAME}:{tls}"]


def test_a_name_that_turns_private_is_refused_on_the_next_request(server, dns):
    plain, _, _ = server
    session = guard_session(requests.Session())
    session.get(f"http://{NAME}:{plain}/", timeout=5)
    dns["answer"] = "10.0.0.5"
    with pytest.raises(UnsafeUrlError):
        session.get(f"http://{NAME}:{plain}/", timeout=5)
    assert len(seen_hosts) == 1


def test_without_pinning_the_name_is_not_resolved_by_the_client(server, dns):
    plain, _, _ = server
    session = guard_session(requests.Session(), pin=False)
    with pytest.raises(requests.ConnectionError):  # the system resolver does not know fixture.test
        session.get(f"http://{NAME}:{plain}/", timeout=5)
