"""Tests for P1-T10: approval endpoint + expire job."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.ids import new_id  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import Approval, Check, Intent, Order, User, Agent  # noqa: E402
from app.paypal import service as paypal_service  # noqa: E402
from app.signing import b64url_encode, utcnow  # noqa: E402
ADMIN = {"X-Admin-Key": "test-operator-key-0123456789"}  # same key as conftest._operator_key

ADVISORY_LOCK_KEY = 912345
UTC = timezone.utc


# --------------------------------------------------------------------------- #
# DB fixtures (same pattern as test_mandates.py)
# --------------------------------------------------------------------------- #

def _test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    from dotenv import dotenv_values
    base = os.environ.get("DATABASE_URL") or dotenv_values(SERVICE_ROOT / ".env").get("DATABASE_URL")
    if not base or base == "__FILL_ME__":
        pytest.fail("DATABASE_URL not configured; cannot locate intentlock_test")
    return make_url(base).set(database="intentlock_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def engine():
    url = _test_db_url()
    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
        try:
            if not c.execute(
                text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": u.database}
            ).scalar():
                c.execute(text(f'CREATE DATABASE "{u.database}"'))
            proc = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=SERVICE_ROOT,
                env={**os.environ, "DATABASE_URL": url},
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                pytest.fail(f"alembic upgrade failed: {proc.stderr[-2000:]}")
        finally:
            c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
    admin.dispose()
    eng = create_engine(url, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def proof_key_b64():
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return b64url_encode(raw)


@pytest.fixture(scope="session")
def wallet_key_b64():
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return b64url_encode(raw)


@pytest.fixture(autouse=True)
def _keys(monkeypatch, proof_key_b64, wallet_key_b64):
    monkeypatch.setattr(settings, "INTENTLOCK_PROOF_PRIVATE_KEY", proof_key_b64)
    monkeypatch.setattr(settings, "INTENTLOCK_WALLET_PRIVATE_KEY", wallet_key_b64)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    paypal_service.reset_mock()


@pytest.fixture()
def db(engine):
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture()
def client(db):
    def _override():
        yield db

    fastapi_app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(fastapi_app, headers=ADMIN)
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _seed(db):
    """Create minimal user, agent, intent."""
    from app.crypto.keys import generate_keypair_b64
    _priv, pub = generate_keypair_b64()
    u = User(id=new_id("usr"), name="Tester")
    db.add(u)
    db.flush()
    a = Agent(id=new_id("agt"), user_id=u.id, name="shopper",
              public_key=pub, device_id="dev1", verified=True)
    db.add(a)
    db.flush()
    i = Intent(
        id=new_id("int"), user_id=u.id, agent_id=a.id,
        request_text="buy milk", signature="sig", signed_at=utcnow(),
    )
    db.add(i)
    db.flush()
    return u, a, i


def _pending_order(db, *, expires_in_min: int = 30) -> tuple[Order, Approval]:
    """Create an order in pending_approval that passes every payment check, with a mock authorization."""
    from conftest import make_capturable_order
    made = make_capturable_order(db, expires_in_min=expires_in_min)
    return made.order, made.approval


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_approve_transitions_to_captured(client, db):
    o, appr = _pending_order(db)
    r = client.post(f"/orders/{o.id}/approval", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "captured"
    ops = [c["op"] for c in paypal_service.mock_calls()]
    assert "capture" in ops
    db.expire_all()
    updated = db.get(Order, o.id)
    assert updated.status == "captured"
    assert updated.capture_id is not None and updated.capture_id.startswith("MOCK-C-")
    updated_appr = db.get(Approval, appr.id)
    assert updated_appr.decision == "approve"
    assert updated_appr.decided_at is not None


def test_decline_transitions_to_voided(client, db):
    o, appr = _pending_order(db)
    r = client.post(f"/orders/{o.id}/approval", json={"decision": "decline"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "voided"
    ops = [c["op"] for c in paypal_service.mock_calls()]
    assert "void" in ops
    db.expire_all()
    updated = db.get(Order, o.id)
    assert updated.status == "voided"
    updated_appr = db.get(Approval, appr.id)
    assert updated_appr.decision == "decline"
    assert updated_appr.decided_at is not None


def test_approval_on_captured_order_returns_409(client, db):
    u, a, i = _seed(db)
    o = Order(
        id=new_id("ord"), intent_id=i.id, agent_id=a.id, user_id=u.id,
        merchant="freshmart", cart_json=[], total=Decimal("3.50"), currency="USD",
        status="captured", decision="capture", reasons=[],
        paypal_order_id="MOCK-O-X", authorization_id="MOCK-A-X", capture_id="MOCK-C-X",
    )
    db.add(o)
    db.flush()
    r = client.post(f"/orders/{o.id}/approval", json={"decision": "approve"})
    assert r.status_code == 409


def test_expired_approval_voided_by_job(db):
    """run_once() should void an order whose approval window has passed."""
    o, appr = _pending_order(db, expires_in_min=-1)  # already expired
    db.flush()

    from app.jobs.expire_approvals import run_once
    # Pass the test session directly so run_once uses the same transaction.
    n = run_once(_db=db)
    assert n >= 1

    db.expire_all()
    updated = db.get(Order, o.id)
    assert updated.status == "voided"
    updated_appr = db.get(Approval, appr.id)
    assert updated_appr.decision == "decline"
    assert updated_appr.decided_at is not None


def test_proof_valid_after_approval(client, db):
    """After approval, GET /orders/{id}/proof returns a proof with valid=True."""
    o, _appr = _pending_order(db)
    r = client.post(f"/orders/{o.id}/approval", json={"decision": "approve"})
    assert r.status_code == 200, r.text

    rp = client.get(f"/orders/{o.id}/proof")
    assert rp.status_code == 200, rp.text
    jp = rp.json()
    assert jp["valid"] is True
    bundle = jp["bundle"]
    # Bundle should reflect the post-approval decision
    assert bundle["decision"] == "capture"
    assert bundle["approval"]["decision"] == "approve"
