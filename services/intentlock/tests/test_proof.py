"""Tests for P1-T11: Proof of Intent build, sign, verify."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVICE_ROOT.parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from conftest import buyer_fields  # noqa: E402
from app.checks import injection_rules  # noqa: E402
from app.config import settings  # noqa: E402
from app.crypto.http_sig import sign_request  # noqa: E402
from app.crypto.keys import generate_keypair_b64  # noqa: E402
from app.db import get_db  # noqa: E402
from app.ids import new_id  # noqa: E402
from app.intents import create_intent  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.mandates import create_mandate  # noqa: E402
from app.models import Agent, Check, Order, Proof, User  # noqa: E402
from app.paypal import service as paypal_service  # noqa: E402
from app.pipeline import adapters, limits  # noqa: E402
from app.proof import build_bundle, issue_proof, latest_proof  # noqa: E402
from app.proof.sign import proof_public_key_b64, sha256_hex, sign_bundle, verify_bundle  # noqa: E402
from app.signing import b64url_encode, canonical_json, load_private_key, public_key_b64, utcnow  # noqa: E402
ADMIN = {"X-Admin-Key": "test-operator-key-0123456789"}  # same key as conftest._operator_key

ADVISORY_LOCK_KEY = 912345
PAGE = REPO_ROOT / "data/lab/pages/normal/normal_01_whole_milk.html"
_ORIG_FETCH = injection_rules.fetch_or_read_html


def _new_key_b64() -> str:
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return b64url_encode(raw)


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
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": u.database}).scalar():
                c.execute(text(f'CREATE DATABASE "{u.database}"'))
            proc = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=SERVICE_ROOT, env={**os.environ, "DATABASE_URL": url},
                capture_output=True, text=True,
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
def keys():
    return SimpleNamespace(wallet=_new_key_b64(), proof=_new_key_b64())


def fake_fetch(url, timeout_s=3.0, *, allow_fixtures=False, allowed_hosts=None):
    if url == "https://freshmart.example/p/milk":
        return PAGE.read_text()
    return _ORIG_FETCH(url, timeout_s, allow_fixtures=allow_fixtures, allowed_hosts=allowed_hosts)


def _yes(request_text, mandate, cart, rule):
    return {"items": [{**i, "explained": "yes", "issue": "none", "source": "llm", "reason": "ok"}
                      for i in rule["items"]], "price_anomaly": False}


@pytest.fixture(autouse=True)
def _env(monkeypatch, keys):
    monkeypatch.setattr(settings, "INTENTLOCK_WALLET_PRIVATE_KEY", keys.wallet)
    monkeypatch.setattr(settings, "INTENTLOCK_PROOF_PRIVATE_KEY", keys.proof)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "RENDER_API_KEY", None)
    monkeypatch.setattr(settings, "RENDER_WORKFLOW_SLUG", None)
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    for k in ("PIPELINE_MODE", "PIPELINE_STUBS", "APPROVAL_TIMEOUT_MIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(limits, "PAY_BACKOFF_S", 0.0)
    paypal_service.reset_mock()
    monkeypatch.setattr(adapters, "_import_injection_classifier", lambda: None)
    monkeypatch.setattr(adapters, "_import_llm_intent_diff", lambda: _yes)
    monkeypatch.setattr(adapters, "_import_graph_risk", lambda: (lambda order: {"score": 5, "signals": []}))
    monkeypatch.setattr(injection_rules, "fetch_or_read_html", fake_fetch)


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


MILK = {"product_id": "p_milk", "title": "Whole Milk 1L", "variant": "1L", "qty": 1, "unit_price": "3.50",
        "currency": "USD", "category": "groceries", "url": "https://freshmart.example/p/milk"}


@pytest.fixture()
def seed(db):
    priv, pub = generate_keypair_b64()
    u = User(id=new_id("usr"), name="Priya", **buyer_fields())
    db.add(u)
    db.flush()
    a = Agent(id=new_id("agt"), user_id=u.id, name="shopper", public_key=pub, device_id="dev1", verified=True)
    db.add(a)
    db.flush()
    m = create_mandate(db, {
        "agent_id": a.id, "categories": ["groceries"], "merchants": ["freshmart"],
        "budget_amount": "50.00", "budget_period": "week", "currency": "USD",
        "starts_at": utcnow() - timedelta(days=1), "expires_at": utcnow() + timedelta(days=30),
    })
    i = create_intent(db, user_id=u.id, agent_id=a.id, request_text="Whole milk from freshmart")
    db.flush()
    return SimpleNamespace(user=u, agent=a, priv=priv, intent=i, mandate=m)


def run_checkout(client, seed, trace_id="trace-xyz"):
    payload = {"intent_id": seed.intent.id, "merchant": "freshmart", "cart": [dict(MILK)],
               "page_urls": ["https://freshmart.example/p/milk"], "shipping_address": None, "trace_id": trace_id}
    raw = json.dumps(payload).encode()
    h = sign_request("POST", "http://testserver/checkout", raw, seed.priv, seed.agent.id)
    r = client.post("/checkout", content=raw, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def manual_order(db, seed):
    o = Order(id=new_id("ord"), intent_id=seed.intent.id, agent_id=seed.agent.id, user_id=seed.user.id,
              merchant="freshmart", cart_json=[dict(MILK)], total=Decimal("3.50"), currency="USD",
              status="captured", decision="capture", page_urls=["https://freshmart.example/p/milk"],
              shipping_address=None, trace_id="trace-1", paypal_order_id="MOCK-O-1",
              authorization_id="MOCK-A-1", capture_id="MOCK-C-1")
    db.add(o)
    db.flush()
    db.add(Check(id=new_id("chk"), order_id=o.id, step="graph_risk", result="pass", score=Decimal("40.00"),
                 details_json={"score": 40.0, "signals": []}, duration_ms=3))
    db.add(Check(id=new_id("chk"), order_id=o.id, step="verify_agent", result="pass", score=None,
                 details_json={"result": "pass"}, duration_ms=1))
    db.flush()
    return o


@pytest.fixture()
def bundle_and_sig(db, seed):
    o = manual_order(db, seed)
    b = build_bundle(db, o.id)
    return b, sign_bundle(b)["signature"]


# --------------------------------------------------------------------------- #
def test_round_trip_valid(bundle_and_sig):
    b, sig = bundle_and_sig
    valid, sha = verify_bundle(b, sig)
    assert valid is True
    assert sha == sha256_hex(b) and len(sha) == 64
    assert b["version"] == 1
    assert b["decision"] == "capture"
    assert b["approval"] is None
    assert b["astropods_trace_id"] == "trace-1"
    assert b["paypal"] == {"order_id": "MOCK-O-1", "authorization_id": "MOCK-A-1", "capture_id": "MOCK-C-1",
                           "void": False}
    assert [c["step"] for c in b["checks"]] == ["verify_agent", "graph_risk"]
    assert b["checks"][1]["score"] == 40 and b["checks"][1]["details"]["score"] == 40
    assert b["mandate"]["id"] == b["mandate"]["id"] and b["mandate"]["signature"]
    assert b["intent"]["signature"] and b["page_urls"] == ["https://freshmart.example/p/milk"]


def test_bundle_contains_no_secrets(bundle_and_sig, keys):
    b, _ = bundle_and_sig
    blob = canonical_json(b).decode()
    assert keys.proof not in blob and keys.wallet not in blob


def test_tamper_price_invalid(bundle_and_sig):
    b, sig = bundle_and_sig
    t = copy.deepcopy(b)
    t["cart"][0]["unit_price"] = "0.01"
    assert verify_bundle(t, sig)[0] is False
    t = copy.deepcopy(b)
    t["order"]["total"] = "0.01"
    assert verify_bundle(t, sig)[0] is False


def test_tamper_decision_invalid(bundle_and_sig):
    b, sig = bundle_and_sig
    t = copy.deepcopy(b)
    t["decision"] = "void"
    assert verify_bundle(t, sig)[0] is False


def test_tamper_check_invalid(bundle_and_sig):
    b, sig = bundle_and_sig
    t = copy.deepcopy(b)
    t["checks"][1]["result"] = "fail"
    assert verify_bundle(t, sig)[0] is False
    t = copy.deepcopy(b)
    t["checks"][1]["score"] = 1
    assert verify_bundle(t, sig)[0] is False


def test_signature_from_other_key_invalid(bundle_and_sig):
    b, _ = bundle_and_sig
    other = load_private_key(_new_key_b64())
    forged = sign_bundle(b, private_key=other)["signature"]
    assert verify_bundle(b, forged)[0] is False
    assert verify_bundle(b, forged, public_key=other.public_key())[0] is True


@pytest.mark.parametrize("sig", ["", "!!!", "AAAA", "x" * 86])
def test_garbage_signature_invalid_never_raises(bundle_and_sig, sig):
    assert verify_bundle(bundle_and_sig[0], sig)[0] is False


def test_canonical_json_stable_across_key_order(bundle_and_sig):
    b, sig = bundle_and_sig

    def reverse(o):
        if isinstance(o, dict):
            return {k: reverse(o[k]) for k in reversed(list(o))}
        if isinstance(o, list):
            return [reverse(x) for x in o]
        return o

    r = reverse(b)
    assert list(r) != list(b)
    assert canonical_json(r) == canonical_json(b)
    assert sha256_hex(r) == sha256_hex(b)
    assert verify_bundle(json.loads(json.dumps(r)), sig)[0] is True


def test_issue_proof_stores_and_reissue_replaces(db, seed):
    o = manual_order(db, seed)
    pid = issue_proof(db, o.id)
    assert pid.startswith("prf_")
    p = latest_proof(db, o.id)
    assert p.id == pid and p.astropods_trace_id == "trace-1"
    first_sha = p.sha256
    assert verify_bundle(p.bundle_json, p.signature)[0] is True  # JSONB round trip stays valid
    o.decision, o.status = "void", "voided"
    pid2 = issue_proof(db, o.id)
    assert db.query(Proof).filter_by(order_id=o.id).count() == 1
    p2 = latest_proof(db, o.id)
    assert p2.bundle_json["decision"] == "void" and p2.bundle_json["paypal"]["void"] is True
    assert p2.sha256 != first_sha and pid2 == pid


def test_pipeline_order_proof_endpoint_valid(client, db, seed):
    j = run_checkout(client, seed)
    assert j["decision"] == "capture"
    db.expire_all()
    steps = {c.step: c for c in db.query(Check).filter_by(order_id=j["order_id"])}
    assert steps["build_proof"].result == "pass"
    r = client.get(f"/orders/{j['order_id']}/proof")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["valid"] is True
    assert d["public_key"] == proof_public_key_b64()
    assert set(d) == {"bundle", "sha256", "signature", "public_key", "valid"}
    b = d["bundle"]
    assert b["decision"] == "capture" and b["astropods_trace_id"] == "trace-xyz"
    assert b["order"]["id"] == j["order_id"] and b["mandate"]["id"] == seed.mandate.id
    assert [c["step"] for c in b["checks"]][:3] == ["verify_agent", "check_mandate", "authorize_payment"]
    # public verify endpoint: untouched bundle valid, tampered invalid
    v = client.post("/proofs/verify", json={"bundle": b, "signature": d["signature"]})
    assert v.status_code == 200 and v.json() == {"valid": True, "sha256": d["sha256"]}
    b["cart"][0]["unit_price"] = "0.01"
    v2 = client.post("/proofs/verify", json={"bundle": b, "signature": d["signature"]})
    assert v2.json()["valid"] is False and v2.json()["sha256"] != d["sha256"]


def test_proof_endpoint_404s(client, db, seed):
    r = client.get("/orders/ord_missing/proof")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    o = manual_order(db, seed)
    r = client.get(f"/orders/{o.id}/proof")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_valid_false_when_stored_row_tampered(client, db, seed):
    o = manual_order(db, seed)
    issue_proof(db, o.id)
    p = latest_proof(db, o.id)
    tampered = copy.deepcopy(p.bundle_json)
    tampered["decision"] = "void"
    p.bundle_json = tampered
    db.flush()
    assert client.get(f"/orders/{o.id}/proof").json()["valid"] is False
