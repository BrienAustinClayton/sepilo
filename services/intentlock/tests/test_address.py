"""/me/address: shipping address, fresh sign-in to change it."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app import auth
from app.config import settings
from app.ids import new_id
from app.models import User, UserSession


@pytest.fixture()
def alice(db):
    u = User(id=new_id("usr"), name="Alice", email="alice@example.com", currency="USD")
    db.add(u)
    db.flush()
    tok = auth._login(db, u, "pytest", True)["token"]
    return u, {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def notices(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(auth.httpx, "post", lambda url, **kw: sent.append(kw["json"]) or _Resp(200, {}))
    return sent


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _body(**over):
    base = {"name": "Alice Smith", "line1": "1 Main St", "city": "Springfield", "postal_code": "12345",
            "country": "us"}
    return {**base, **over}


def test_empty_address_for_new_user(client, alice):
    _, h = alice
    assert client.get("/me/address", headers=h).json() == {"address": None, "updated_at": None}


def test_put_then_get_returns_the_address(client, alice, notices):
    _, h = alice
    r = client.put("/me/address", headers=h, json=_body(line2="Apt 4", phone="+1 (555) 010-9999"))
    assert r.status_code == 200, r.text
    out = client.get("/me/address", headers=h).json()
    assert out["address"] == {"name": "Alice Smith", "line1": "1 Main St", "line2": "Apt 4",
                              "city": "Springfield", "postal_code": "12345", "country": "US",
                              "phone": "+1 (555) 010-9999"}
    assert out["updated_at"].endswith("Z")
    assert out == r.json()


def test_optional_fields_are_not_stored_when_absent(client, alice, notices):
    _, h = alice
    client.put("/me/address", headers=h, json=_body())
    assert "line2" not in client.get("/me/address", headers=h).json()["address"]


def test_change_sends_a_security_notice(client, alice, notices):
    _, h = alice
    client.put("/me/address", headers=h, json=_body())
    assert notices and notices[0]["to"] == ["alice@example.com"]
    assert "Springfield, US" in notices[0]["text"]


def test_bad_country_is_rejected(client, alice):
    _, h = alice
    assert client.put("/me/address", headers=h, json=_body(country="USA")).status_code == 422


def test_extra_field_is_rejected(client, alice):
    _, h = alice
    assert client.put("/me/address", headers=h, json=_body(is_admin=True)).status_code == 422


def test_changing_address_needs_a_fresh_sign_in(client, db, alice, notices):
    user, h = alice
    sess = db.query(UserSession).filter_by(user_id=user.id).one()
    sess.created_at = sess.created_at - timedelta(minutes=30)
    db.commit()
    r = client.put("/me/address", headers=h, json=_body())
    assert r.status_code == 403 and r.json()["error"] == "reauth_required"
    assert client.get("/me/address", headers=h).json()["address"] is None


def test_address_requires_session(client):
    assert client.get("/me/address").status_code == 401
    assert client.put("/me/address", json=_body()).status_code == 401
