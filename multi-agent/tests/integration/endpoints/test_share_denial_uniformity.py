"""A share invitation the caller has no part in answers exactly like a missing one."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from inbound.flask.endpoints import register_all_endpoints
from mas.core.identity import Identity
from mas.sharing.models import ShareInvite, ShareItemKind
from mas.sharing.service import ShareService

SENDER, RECIPIENT, STRANGER = "sender", "recipient", "stranger"
BASE = "/api/shares"


def _invite() -> ShareInvite:
    return ShareInvite(
        share_id="s1", sender_identity=Identity.user(SENDER), recipient_identity=Identity.user(RECIPIENT),
        item_kind=ShareItemKind.RESOURCE, item_id="r1", item_name="r",
    )


@pytest.fixture
def client():
    repo = Mock()

    def get(share_id):
        if share_id != "s1":
            raise KeyError(f"Share invite not found: {share_id}")
        return _invite()

    repo.get.side_effect = get
    service = ShareService(repo, Mock())
    app = Flask(__name__)
    app.secret_key = "s"
    app.config["admin_allowed_users"] = []
    app.container = SimpleNamespace(
        share_service=service, identity_provider=Mock(is_member=Mock(return_value=False)), admin_config_reader=None,
    )
    register_all_endpoints(app)
    return app.test_client()


def _h(user: str) -> dict:
    return {"X-Authenticated-User": user}


@pytest.mark.parametrize("path", ["share.accept", "share.decline", "share.cancel"])
def test_a_stranger_gets_the_answer_for_a_missing_invite(client, path):
    denied = client.post(f"{BASE}/{path}", json={"shareId": "s1"}, headers=_h(STRANGER))
    missing = client.post(f"{BASE}/{path}", json={"shareId": "nope"}, headers=_h(STRANGER))
    assert denied.status_code == missing.status_code == 404
    assert denied.get_json() == missing.get_json()


def test_the_wrong_side_of_the_invite_is_refused_like_a_stranger(client):
    # the sender may not accept its own invitation, the recipient may not cancel it
    assert client.post(f"{BASE}/share.accept", json={"shareId": "s1"}, headers=_h(SENDER)).status_code == 404
    assert client.post(f"{BASE}/share.cancel", json={"shareId": "s1"}, headers=_h(RECIPIENT)).status_code == 404


def test_get_by_a_stranger_looks_like_a_missing_invite(client):
    denied = client.get(f"{BASE}/share.get?shareId=s1", headers=_h(STRANGER))
    missing = client.get(f"{BASE}/share.get?shareId=nope", headers=_h(STRANGER))
    assert denied.status_code == missing.status_code == 404
    assert denied.get_json() == missing.get_json()


def test_the_parties_still_reach_their_invitation(client):
    assert client.get(f"{BASE}/share.get?shareId=s1", headers=_h(SENDER)).status_code == 200
    assert client.get(f"{BASE}/share.get?shareId=s1", headers=_h(RECIPIENT)).status_code == 200
    assert client.post(f"{BASE}/share.cancel", json={"shareId": "s1"}, headers=_h(SENDER)).status_code == 200
