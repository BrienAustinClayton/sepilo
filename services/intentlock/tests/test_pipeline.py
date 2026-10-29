"""Tests for P1-T08: check pipeline (local mode, PayPal mocked)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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
from app.models import Agent, Approval, Check, Order, User  # noqa: E402
from app.paypal import service as paypal_service  # noqa: E402
from app.paypal.service import PayPalError  # noqa: E402
from app.pipeline import adapters, core, limits, runner, stubs  # noqa: E402
from app.pipeline.core import run_pipeline  # noqa: E402
from app.pipeline.runner import LocalExecutor  # noqa: E402
from app.pipeline.steps import ALL_STEPS, record_check  # noqa: E402
from app.signing import b64url_encode, utcnow  # noqa: E402
ADMIN = {"X-Admin-Key": "test-operator-key-0123456789"}  # same key as conftest._operator_key

ADVISORY_LOCK_KEY = 912345
PAGES = {
    "https://freshmart.example/p/milk": REPO_ROOT / "data/lab/pages/normal/normal_01_whole_milk.html",
    "https://freshmart.example/p/attack": REPO_ROOT / "data/lab/pages/attack/attack_01_display_none.html",
}
_ORIG_FETCH = injection_rules.fetch_or_read_html


# --------------------------------------------------------------------------- #
# Fixtures
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
def wallet_key_b64():
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return b64url_encode(raw)


def fake_fetch(url, timeout_s=3.0, *, allow_fixtures=False, allowed_hosts=None):
    if url in PAGES:
        return PAGES[url].read_text()
    return _ORIG_FETCH(url, timeout_s, allow_fixtures=allow_fixtures, allowed_hosts=allowed_hosts)


@pytest.fixture(autouse=True)
def _env(monkeypatch, wallet_key_b64):
    monkeypatch.setattr(settings, "INTENTLOCK_WALLET_PRIVATE_KEY", wallet_key_b64)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "RENDER_API_KEY", None)
    monkeypatch.setattr(settings, "RENDER_WORKFLOW_SLUG", None)
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    for k in ("PIPELINE_MODE", "PIPELINE_STUBS", "APPROVAL_TIMEOUT_MIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(limits, "PAY_BACKOFF_S", 0.0)
    paypal_service.reset_mock()
    monkeypatch.setattr(adapters, "_import_injection_classifier", lambda: None)
    monkeypatch.setattr(adapters, "_import_llm_intent_diff", lambda: None)
    monkeypatch.setattr(adapters, "_import_graph_risk", lambda: None)
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


def _make_seed(db, name="Priya"):
    priv, pub = generate_keypair_b64()
    u = User(id=new_id("usr"), name=name, **buyer_fields())
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


@pytest.fixture()
def seed(db):
    return _make_seed(db)


MILK = {"product_id": "p_milk", "title": "Whole Milk 1L", "variant": "1L", "qty": 1, "unit_price": "3.50",
        "currency": "USD", "category": "groceries", "url": "https://freshmart.example/p/milk"}


def body(seed, **over):
    d = {"intent_id": seed.intent.id, "merchant": "freshmart", "cart": [dict(MILK)],
         "page_urls": ["https://freshmart.example/p/milk"], "shipping_address": None, "trace_id": "trace-1"}
    d.update(over)
    return d


def post(client, seed, payload):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    h = sign_request("POST", "http://testserver/checkout", raw, seed.priv, seed.agent.id)
    return client.post("/checkout", content=raw, headers=h)


def clean_graph(monkeypatch, score=5, signals=()):
    monkeypatch.setattr(adapters, "_import_graph_risk",
                        lambda: (lambda order: {"score": score, "signals": list(signals)}))


def yes_hook(monkeypatch):
    def fake(rt, m, cart, rule):
        return {"items": [{**i, "explained": "yes", "issue": "none", "source": "llm", "reason": "ok"}
                          for i in rule["items"]], "price_anomaly": False}

    monkeypatch.setattr(adapters, "_import_llm_intent_diff", lambda: fake)


def checks(db, order_id):
    db.expire_all()
    return {c.step: c for c in db.query(Check).filter_by(order_id=order_id)}


def ops():
    return [c["op"] for c in paypal_service.mock_calls()]


def order_of(db, oid):
    db.expire_all()
    return db.get(Order, oid)


def make_order(db, seed):
    o = Order(id=new_id("ord"), intent_id=seed.intent.id, agent_id=seed.agent.id, user_id=seed.user.id,
              merchant="freshmart", cart_json=[dict(MILK)], total=Decimal("3.50"), currency="USD",
              status="received", page_urls=["https://freshmart.example/p/milk"], shipping_address=None,
              trace_id="t")
    db.add(o)
    db.flush()
    record_check(db, o.id, "verify_agent", "pass", {"result": "pass", "reason": "ok", "keyid": seed.agent.id}, 1)
    db.commit()
    return o.id


def ok(client, seed, **over):
    r = post(client, seed, body(seed, **over))
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_normal_order_captured_end_to_end(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    t0 = time.perf_counter()
    r = post(client, seed, body(seed))
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["status"], j["decision"], j["reasons"]) == ("captured", "capture", [])
    assert elapsed < 6.0
    assert ops() == ["authorize", "capture"]
    o = order_of(db, j["order_id"])
    assert o.user_id == seed.intent.user_id
    assert o.capture_id.startswith("MOCK-C-")
    assert o.page_urls == ["https://freshmart.example/p/milk"]
    assert o.trace_id == "trace-1"
    assert o.total == Decimal("3.50")


def test_checks_rows_one_per_step_with_duration(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    c = checks(db, j["order_id"])
    assert set(c) == set(ALL_STEPS) | {"preflight"}
    assert c["preflight"].result == "pass" and c["preflight"].details_json["total"] == 32
    assert all(isinstance(r.duration_ms, int) and r.duration_ms >= 0 for r in c.values())
    assert c["verify_agent"].result == "pass"
    assert c["decide"].result == "pass"
    assert c["build_proof"].result in ("pass", "skipped")
    assert "hidden_text" not in c["scan_injection"].details_json
    assert "visible_text" not in c["scan_injection"].details_json


def test_status_transitions_local(db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    oid = make_order(db, seed)
    out = asyncio.run(run_pipeline(db, oid, LocalExecutor(db)))
    assert out.status_history == ["authorized", "checking", "captured"]


def test_mandate_breach_over_budget_rejected_zero_paypal_calls(client, db, seed, monkeypatch):
    mock = MagicMock(side_effect=AssertionError("no paypal"))
    monkeypatch.setattr(paypal_service, "authorize", mock)
    cart = [{**MILK, "unit_price": "60.00"}]
    j = ok(client, seed, cart=cart)
    assert j["status"] == "rejected" and j["decision"] == "reject"
    assert j["reasons"] == ["Total exceeds the remaining mandate budget"]
    assert ops() == []
    mock.assert_not_called()
    c = checks(db, j["order_id"])
    assert c["check_mandate"].result == "fail"
    for s in ("authorize_payment", "scan_injection", "intent_diff", "graph_risk", "capture_or_void"):
        assert c[s].result == "skipped", s
    assert not any("60.00" in r for r in j["reasons"])


def test_reasons_never_echo_mandate_message(client, db, seed):
    cart = [{**MILK, "category": "evil_cat"}]
    j = ok(client, seed, cart=cart)
    assert j["reasons"] == ["A cart category is not allowed by the mandate"]
    c = checks(db, j["order_id"])
    assert "evil_cat" in c["check_mandate"].details_json["message"]
    assert not any("evil_cat" in r for r in j["reasons"])


def test_merchant_breach_rejected(client, seed):
    j = ok(client, seed, merchant="dealsdaily")
    assert j["reasons"] == ["Merchant is not allowed by the mandate"]
    assert ops() == []


def test_injection_high_confidence_voided(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed, page_urls=["https://freshmart.example/p/attack"])
    assert j["status"] == "voided" and j["decision"] == "void"
    assert ops() == ["authorize", "void"]
    c = checks(db, j["order_id"])
    assert c["scan_injection"].result == "flag"
    assert any(r.startswith("Hidden instructions (") for r in j["reasons"])
    for f in c["scan_injection"].details_json["findings"]:
        if f["snippet"]:
            assert not any(f["snippet"] in r for r in j["reasons"])


def _hold_setup(client, seed, monkeypatch):
    clean_graph(monkeypatch)
    return ok(client, seed)


def test_unexplained_line_holds_with_approval(client, db, seed, monkeypatch):
    j = _hold_setup(client, seed, monkeypatch)
    assert j["status"] == "pending_approval" and j["decision"] == "hold"
    assert j["reasons"] == ["'Whole Milk 1L' was not explained by your request"]
    assert ops() == ["authorize"]
    db.expire_all()
    appr = db.query(Approval).filter_by(order_id=j["order_id"]).all()
    assert len(appr) == 1
    assert appr[0].decision is None
    assert appr[0].expires_at - appr[0].requested_at == timedelta(minutes=30)
    assert checks(db, j["order_id"])["capture_or_void"].result == "flag"


def test_approval_timeout_env_override(client, db, seed, monkeypatch):
    monkeypatch.setenv("APPROVAL_TIMEOUT_MIN", "1")
    j = _hold_setup(client, seed, monkeypatch)
    db.expire_all()
    a = db.query(Approval).filter_by(order_id=j["order_id"]).one()
    assert a.expires_at - a.requested_at == timedelta(minutes=1)


def test_graph_missing_holds(client, db, seed, monkeypatch):
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert j["status"] == "pending_approval"
    assert "Risk check did not run; needs your review" in j["reasons"]
    assert checks(db, j["order_id"])["graph_risk"].result == "error"


def test_graph_high_score_voided(client, seed, monkeypatch):
    clean_graph(monkeypatch, score=75, signals=[{"name": "bot_farm", "weight": 75, "evidence": ["agt_x"]}])
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert j["decision"] == "void"
    assert ops() == ["authorize", "void"]
    assert j["reasons"][0] == "Risk score 75 exceeds void threshold"


def test_local_file_page_url_not_read_and_holds(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed, page_urls=["/etc/passwd"])
    assert j["status"] == "pending_approval"
    assert checks(db, j["order_id"])["scan_injection"].result == "error"
    assert "Injection scan did not run; needs your review" in j["reasons"]


def test_empty_page_urls_holds(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed, page_urls=[])
    assert j["status"] == "pending_approval"
    assert checks(db, j["order_id"])["scan_injection"].result == "error"


def test_unsigned_checkout_401_creates_no_order(client, db, seed):
    n = db.query(Order).count()
    r = client.post("/checkout", json=body(seed))
    assert r.status_code == 401
    assert r.json() == {"error": "agent_verification_failed", "reason": "bad_signature"}
    assert db.query(Order).count() == n


def test_intent_of_other_agent_403_no_order(client, db, seed):
    other = _make_seed(db, "Other")
    n = db.query(Order).count()
    r = post(client, seed, body(seed, intent_id=other.intent.id))
    assert r.status_code == 403
    assert r.json()["error"] == "intent_mismatch"
    assert db.query(Order).count() == n


def test_unknown_intent_404(client, seed):
    r = post(client, seed, body(seed, intent_id="int_missing"))
    assert r.status_code == 404
    assert r.json() == {"error": "not_found", "reason": "intent not found"}


def test_invalid_body_422(client, seed):
    bad = [
        body(seed, cart=[{**MILK, "unit_price": 3.5}]),
        body(seed, cart=[{**MILK, "qty": 0}]),
        b"not json",
    ]
    for p in bad:
        r = post(client, seed, p)
        assert r.status_code == 422, r.text
        assert r.json() == {"error": "unprocessable", "reason": "invalid checkout body"}


def test_authorize_retry_then_success(client, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    paypal_service.mock_fail_next("authorize", PayPalError("INTERNAL_SERVER_ERROR", retryable=True))
    j = ok(client, seed)
    assert j["status"] == "captured"
    assert ops() == ["authorize", "authorize", "capture"]


def test_authorize_non_retryable_failure_marks_failed(client, db, seed):
    paypal_service.mock_fail_next("authorize", PayPalError("PAYER_ACTION_REQUIRED"), times=3)
    j = ok(client, seed)
    assert j["status"] == "failed" and j["decision"] is None
    assert j["reasons"] == ["Payment could not be authorized"]
    assert ops() == ["authorize"]
    c = checks(db, j["order_id"])["authorize_payment"]
    assert c.result == "error" and c.details_json["error"] == "PAYER_ACTION_REQUIRED"


def test_capture_failure_voids_and_fails(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    paypal_service.mock_fail_next("capture", PayPalError("INTERNAL"))
    j = ok(client, seed)
    assert j["status"] == "failed"
    assert ops() == ["authorize", "capture", "void"]
    assert checks(db, j["order_id"])["capture_or_void"].details_json["voided"] is True


def test_ai_step_timeout_holds(client, db, seed, monkeypatch):
    monkeypatch.setattr(limits, "STEP_TIMEOUT_S", 0.2)

    def slow(order):
        time.sleep(0.6)
        return {"score": 5, "signals": []}

    monkeypatch.setattr(adapters, "_import_graph_risk", lambda: slow)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert j["status"] == "pending_approval"
    assert checks(db, j["order_id"])["graph_risk"].details_json["error"] == "timeout"


def test_ai_step_exception_retried_once(client, db, seed, monkeypatch):
    calls = {"n": 0}

    def flaky(order):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"score": 5, "signals": []}

    monkeypatch.setattr(adapters, "_import_graph_risk", lambda: flaky)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert j["status"] == "captured"
    assert checks(db, j["order_id"])["graph_risk"].details_json["attempts"] == 2


def test_llm_hook_cannot_override_deterministic_flag(client, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    gc = {"product_id": "p_gc", "title": "Gift Card 50", "qty": 1, "unit_price": "10.00",
          "currency": "USD", "category": "groceries", "url": None}
    j = ok(client, seed, cart=[dict(MILK), gc])
    assert j["decision"] == "hold"
    assert "'Gift Card 50' is not in your request" in j["reasons"]
    assert ops() == ["authorize"]


def test_merge_intent_diff_unit():
    rule = {"items": [{"product_id": "p1", "title": "Milk", "explained": "uncertain", "issue": "none",
                       "source": "deterministic", "reason": "r"}], "price_anomaly": False}
    assert adapters.merge_intent_diff(rule, {"items": []}) == rule
    bad = {"items": [{"explained": "maybe", "issue": "none"}]}
    assert adapters.merge_intent_diff(rule, bad)["items"][0] == rule["items"][0]
    good = {"items": [{"explained": "yes", "issue": "none", "reason": "fine", "title": "EVIL",
                       "product_id": "evil"}]}
    m = adapters.merge_intent_diff(rule, good)["items"][0]
    assert m["source"] == "llm" and m["explained"] == "yes"
    assert m["title"] == "Milk" and m["product_id"] == "p1"
    priced = {"items": [{"product_id": "p1", "title": "Milk", "explained": "uncertain", "issue": "price"}],
              "price_anomaly": False}
    out = adapters.merge_intent_diff(priced, {"items": [{"explained": "yes", "issue": "none"}]})
    assert out["items"][0] == priced["items"][0]


def test_duplicate_run_is_claimed_once(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    out = asyncio.run(run_pipeline(db, j["order_id"], LocalExecutor(db)))
    assert out.already_processed is True
    assert out.status == "captured"
    assert ops() == ["authorize", "capture"]


def test_unexpected_error_after_authorize_holds(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    real = core.decide

    def raising(verify, mandate, injection, intent_diff, graph):
        if injection is not None:
            raise RuntimeError("boom")
        return real(verify, mandate, injection, intent_diff, graph)

    monkeypatch.setattr(core, "decide", raising)
    j = ok(client, seed)
    assert j["status"] == "pending_approval" and j["decision"] == "hold"
    assert j["reasons"] == ["Policy check could not be completed; needs your review"]
    db.expire_all()
    assert db.query(Approval).filter_by(order_id=j["order_id"]).count() == 1
    assert ops() == ["authorize"]


def test_stubs_enabled_truth_table(monkeypatch):
    monkeypatch.setenv("PIPELINE_STUBS", "1")
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    assert limits.stubs_enabled() is True
    assert adapters.load_graph_risk() is stubs.graph_risk_stub
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    assert limits.stubs_enabled() is False
    assert adapters.load_graph_risk() is None
    monkeypatch.delenv("PIPELINE_STUBS")
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    assert limits.stubs_enabled() is False
    assert adapters.load_graph_risk() is None


def test_stub_mode_normal_captured(client, seed, monkeypatch):
    monkeypatch.setenv("PIPELINE_STUBS", "1")
    j = ok(client, seed)
    assert j["status"] == "captured"


def test_sandbox_mode_without_module_fails_safely(client, db, seed, monkeypatch):
    if (SERVICE_ROOT / "app/paypal/sandbox.py").exists():
        pytest.skip("sandbox module exists")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    j = ok(client, seed)
    assert j["status"] == "failed"
    assert checks(db, j["order_id"])["authorize_payment"].details_json["error"] == "sandbox_not_implemented"


def test_render_mode_not_configured_falls_back_to_local(client, seed, monkeypatch, caplog):
    monkeypatch.setenv("PIPELINE_MODE", "render")
    caplog.set_level(logging.WARNING, logger="intentlock.pipeline")
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert j["status"] == "captured"
    assert "pipeline.render_unavailable" in caplog.text and "not_configured" in caplog.text


class FakeWorkflows:
    def __init__(self, start_exc=None, on_first_poll=None, status="running"):
        self.start_exc, self.on_first_poll, self.status = start_exc, on_first_poll, status
        self.started, self.cancelled, self._polled = None, [], False

    async def start_task(self, name, data):
        self.started = (name, data)
        if self.start_exc:
            raise self.start_exc
        return SimpleNamespace(id="trn-test")

    async def get_task_run(self, run_id):
        if not self._polled and self.on_first_poll:
            self._polled = True
            await self.on_first_poll(self.started[1][0])
        return SimpleNamespace(status=self.status)

    async def cancel_task_run(self, run_id):
        self.cancelled.append(run_id)


class FakeRender:
    def __init__(self, wf):
        self.workflows = wf


def _render_cfg(monkeypatch, wf):
    monkeypatch.setenv("PIPELINE_MODE", "render")
    monkeypatch.setattr(settings, "RENDER_API_KEY", "k")
    monkeypatch.setattr(settings, "RENDER_WORKFLOW_SLUG", "wf")
    monkeypatch.setattr(runner, "_render_client", lambda token: FakeRender(wf))


def test_render_mode_start_failure_falls_back(client, seed, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="intentlock.pipeline")
    _render_cfg(monkeypatch, FakeWorkflows(start_exc=RuntimeError("down")))
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert j["status"] == "captured"
    assert "start_failed" in caplog.text


def test_render_mode_timeout_unstarted_cancels_and_runs_local(client, seed, monkeypatch):
    wf = FakeWorkflows(status="running")
    _render_cfg(monkeypatch, wf)
    monkeypatch.setattr(limits, "RENDER_WAIT_S", 0.3)
    monkeypatch.setattr(limits, "RENDER_POLL_S", 0.05)
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert wf.started == ("wf/run_checkout", [j["order_id"], False])
    assert wf.cancelled == ["trn-test"]
    assert j["status"] == "captured"
    assert ops() == ["authorize", "capture"]


def test_render_mode_success_reads_outcome_from_db(client, db, seed, monkeypatch):
    async def worker(order_id):
        await run_pipeline(db, order_id, LocalExecutor(db))

    wf = FakeWorkflows(on_first_poll=worker, status="succeeded")
    _render_cfg(monkeypatch, wf)
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    j = ok(client, seed)
    assert j["status"] == "captured"
    assert ops() == ["authorize", "capture"]


def test_workflow_module_registers_tasks():
    pytest.importorskip("render")
    import workflows.intentlock_checks as wf

    tasks = (wf.run_checkout_task, wf.authorize_payment, wf.capture_payment, wf.void_payment,
             wf.scan_injection_task, wf.intent_diff_task, wf.graph_risk_task)
    assert {t.name for t in tasks} == {"run_checkout", "authorize_payment", "capture_payment", "void_payment",
                                       "scan_injection", "intent_diff", "graph_risk"}


def test_app_imports_without_render():
    r = subprocess.run(
        [sys.executable, "-c", "import app.main, app.pipeline.runner, sys; assert 'render' not in sys.modules"],
        cwd=SERVICE_ROOT, env={**os.environ, "PYTHONPATH": str(SERVICE_ROOT)}, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-500:]


def test_paypal_mock_state_machine():
    o = SimpleNamespace(id="ord_x", total=Decimal("3.50"), currency="USD", cart_json=[])
    assert paypal_service.authorize(o) == paypal_service.authorize(o)
    _, aid = paypal_service.authorize(o)
    c1 = paypal_service.capture(aid)
    assert paypal_service.capture(aid) == c1
    with pytest.raises(PayPalError) as e:
        paypal_service.void(aid)
    assert e.value.code == "AUTHORIZATION_ALREADY_CAPTURED"
    o2 = SimpleNamespace(id="ord_y", total=Decimal("1.00"), currency="USD", cart_json=[])
    _, aid2 = paypal_service.authorize(o2)
    paypal_service.void(aid2)
    with pytest.raises(PayPalError) as e:
        paypal_service.capture(aid2)
    assert e.value.code == "AUTHORIZATION_VOIDED"
    o3 = SimpleNamespace(id="ord_z", total=Decimal("0"), currency="USD", cart_json=[])
    with pytest.raises(PayPalError) as e:
        paypal_service.authorize(o3)
    assert e.value.code == "INVALID_AMOUNT"


# --------------------------------------------------------------------------- #
# Buyer approval in PayPal (no saved PayPal account yet)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def buyer_flow(db, monkeypatch):
    from app.api import paypal_return

    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")  # also the signed checkout URL
    monkeypatch.setattr(settings, "WEB_ORIGIN", "https://shop.example.test")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.notify.httpx.post", lambda *a, **k: SimpleNamespace(status_code=200, text=""))

    async def resume(order_id):
        await core.resume_after_payment(db, order_id, LocalExecutor(db))

    monkeypatch.setattr(paypal_return, "resume_checkout", resume)
    paypal_service.mock_fail_next("authorize", PayPalError("no_payment_token"))


def _awaiting(client, db, seed):
    j = ok(client, seed)
    assert (j["status"], j["decision"]) == ("awaiting_payment", None)
    return order_of(db, j["order_id"])


def test_no_saved_paypal_asks_buyer_to_approve(client, db, seed, buyer_flow):
    o = _awaiting(client, db, seed)
    assert ops() == ["authorize", "create_checkout"]
    assert o.paypal_order_id.startswith("MOCK-O-")
    assert o.payer_action_url.startswith(f"http://testserver/paypal/return?order_id={o.id}")
    c = checks(db, o.id)
    assert c["authorize_payment"].result == "flag"
    assert c["authorize_payment"].details_json["action"] == "buyer_approval"
    assert "scan_injection" not in c and "capture_or_void" not in c
    view = client.get(f"/orders/{o.id}").json()
    assert view["status"] == "awaiting_payment" and view["pay_url"] == o.payer_action_url


def test_buyer_approval_authorizes_checks_and_captures(client, db, seed, buyer_flow, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    o = _awaiting(client, db, seed)
    r = client.get(f"/paypal/return?order_id={o.id}&token={o.paypal_order_id}&PayerID=X", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"https://shop.example.test/orders/{o.id}?paypal=approved"
    o = order_of(db, o.id)
    assert (o.status, o.decision) == ("captured", "capture")
    assert o.authorization_id.startswith("MOCK-A-") and o.capture_id and o.payer_action_url is None
    assert ops() == ["authorize", "create_checkout", "authorize_approved", "capture"]
    c = checks(db, o.id)
    assert c["authorize_payment"].result == "pass"
    assert c["authorize_payment"].details_json["saved_for_later"] is True
    assert c["decide"].details_json["decision"] == "capture"
    db.expire_all()
    assert db.get(User, seed.user.id).paypal_payment_token.startswith("MOCK-PT-")
    again = client.get(f"/paypal/return?order_id={o.id}&token={o.paypal_order_id}", follow_redirects=False)
    assert again.headers["location"].endswith("paypal=done")
    assert ops().count("authorize_approved") == 1


def test_buyer_cancel_keeps_order_waiting(client, db, seed, buyer_flow):
    o = _awaiting(client, db, seed)
    r = client.get(f"/paypal/return?order_id={o.id}&token={o.paypal_order_id}&cancelled=1", follow_redirects=False)
    assert r.headers["location"].endswith("paypal=cancelled")
    assert order_of(db, o.id).status == "awaiting_payment"
    assert "authorize_approved" not in ops()


def test_buyer_return_with_wrong_token_is_ignored(client, db, seed, buyer_flow):
    o = _awaiting(client, db, seed)
    r = client.get(f"/paypal/return?order_id={o.id}&token=SOMEONEELSE", follow_redirects=False)
    assert r.headers["location"].endswith("paypal=error")
    assert order_of(db, o.id).status == "awaiting_payment"
    bad = client.get("/paypal/return?order_id=../../x", follow_redirects=False)
    assert bad.status_code == 303 and bad.headers["location"] == "https://shop.example.test/orders"


def test_buyer_not_yet_approved_stays_waiting(client, db, seed, buyer_flow):
    o = _awaiting(client, db, seed)
    paypal_service.mock_fail_next("authorize_approved", PayPalError("ORDER_NOT_APPROVED"))
    r = client.get(f"/paypal/return?order_id={o.id}&token={o.paypal_order_id}", follow_redirects=False)
    assert r.headers["location"].endswith("paypal=cancelled")
    assert order_of(db, o.id).status == "awaiting_payment"


def test_buyer_authorization_failure_fails_order(client, db, seed, buyer_flow):
    o = _awaiting(client, db, seed)
    paypal_service.mock_fail_next("authorize_approved", PayPalError("INSTRUMENT_DECLINED"))
    r = client.get(f"/paypal/return?order_id={o.id}&token={o.paypal_order_id}", follow_redirects=False)
    assert r.headers["location"].endswith("paypal=failed")
    o = order_of(db, o.id)
    assert o.status == "failed" and o.reasons == ["Payment could not be authorized"]
    assert checks(db, o.id)["authorize_payment"].details_json["error"] == "INSTRUMENT_DECLINED"


def test_buyer_approval_creation_failure_fails_order(client, db, seed, buyer_flow):
    paypal_service.mock_fail_next("create_checkout", PayPalError("UNPROCESSABLE_ENTITY"))
    j = ok(client, seed)
    assert j["status"] == "failed"
    assert checks(db, j["order_id"])["authorize_payment"].details_json["error"] == "UNPROCESSABLE_ENTITY"


def test_waiting_order_holds_budget_and_expires(client, db, seed, buyer_flow):
    from app.jobs import expire_approvals
    from app.mandates import spent_in_period

    o = _awaiting(client, db, seed)
    assert spent_in_period(db, seed.mandate) == Decimal("3.50")
    o.created_at = utcnow() - timedelta(hours=4)
    db.commit()
    expire_approvals.run_once(db)
    o = order_of(db, o.id)
    assert o.status == "failed" and o.payer_action_url is None
    assert spent_in_period(db, seed.mandate) == Decimal("0")


def test_saved_payment_only_counts_real_paypal_ids_in_sandbox(monkeypatch):
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    assert paypal_service.has_saved_payment("MOCK-PT-ABC") is False
    assert paypal_service.has_saved_payment("8kk8451t") is True
    assert paypal_service.has_saved_payment(None) is False
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    assert paypal_service.has_saved_payment("MOCK-PT-ABC") is True


def test_refused_saved_paypal_falls_back_to_buyer_in_sandbox(client, db, seed, buyer_flow, monkeypatch):
    paypal_service.reset_mock()
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    monkeypatch.setattr(paypal_service, "_impl", lambda: None)  # still the mock PayPal, but sandbox rules
    paypal_service.mock_fail_next("authorize", PayPalError("PAYEE_ACCOUNT_RESTRICTED"))
    o = _awaiting(client, db, seed)
    assert ops() == ["authorize", "create_checkout"]
    assert o.status == "awaiting_payment"


def test_agent_reads_only_its_own_intent_with_a_signature(client, db, seed):  # client: DB override
    from app.main import app

    url = f"/intents/{seed.intent.id}"
    anon = TestClient(app)
    assert anon.get(url).status_code == 401
    h = sign_request("GET", f"http://testserver{url}", b"", seed.priv, seed.agent.id)
    r = anon.get(url, headers=h)
    assert r.status_code == 200 and r.json()["request_text"] == seed.intent.request_text
    other = _make_seed(db, name="Ravi")
    h2 = sign_request("GET", f"http://testserver{url}", b"", other.priv, other.agent.id)
    assert anon.get(url, headers=h2).status_code == 404


def test_lab_test_key_agent_cannot_use_real_checkout(client, db, seed):
    from app.crypto.vector import VECTOR_PRIVATE_KEY, VECTOR_PUBLIC_KEY

    seed.agent.public_key = VECTOR_PUBLIC_KEY
    db.commit()
    raw = json.dumps(body(seed)).encode()
    h = sign_request("POST", "http://testserver/checkout", raw, VECTOR_PRIVATE_KEY, seed.agent.id)
    r = client.post("/checkout", content=raw, headers=h)
    assert r.status_code == 403 and r.json()["error"] == "lab_agent"


# --------------------------------------------------------------------------- #
# Server-side truth at checkout, approved-cart lock, one order per request
# --------------------------------------------------------------------------- #
def _channel3(monkeypatch, *, price=3.5, domain="freshmart.com", category="food-beverages", stock="InStock"):
    from app import product_truth

    def fake(pid, db=None, fresh=False):
        assert fresh is True
        return {"id": pid, "title": "Whole Milk 1L (Channel3)", "category": {"path": [{"slug": category}]},
                "offers": [{"domain": domain, "availability": stock, "url": f"https://{domain}/p/{pid}",
                            "price": {"price": price, "currency": "USD"}}]}

    monkeypatch.setattr(product_truth, "get_product", fake)


@pytest.fixture()
def real_seed(db):
    """Seed whose rule allows the Channel3 category and store used by _channel3."""
    s = _make_seed(db, name="Mia")
    s.mandate.categories = ["food-beverages"]
    s.mandate.merchants = ["freshmart.com"]
    db.commit()
    return s


def _cart_body(seed, **line):
    return body(seed, merchant="freshmart.com", cart=[{**MILK, **line}])


@pytest.mark.real_catalog_check
def test_checkout_price_must_match_channel3(client, db, real_seed, monkeypatch):
    _channel3(monkeypatch, price=4.10)
    r = post(client, real_seed, _cart_body(real_seed))
    assert r.status_code == 409 and r.json()["error"] == "cart_not_verified"
    assert "$4.10" in r.json()["reason"]
    assert db.query(Order).filter_by(intent_id=real_seed.intent.id).count() == 0


@pytest.mark.real_catalog_check
def test_checkout_store_must_sell_the_product(client, real_seed, monkeypatch):
    _channel3(monkeypatch, domain="other-shop.com")
    r = post(client, real_seed, _cart_body(real_seed))
    assert r.status_code == 409 and "isn't sold by freshmart.com" in r.json()["reason"]
    _channel3(monkeypatch, stock="OutOfStock")
    assert "out of stock" in post(client, real_seed, _cart_body(real_seed)).json()["reason"]


@pytest.mark.real_catalog_check
def test_checkout_uses_channel3_category_not_the_agents(client, db, real_seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    _channel3(monkeypatch, category="electronics")  # the agent claims "groceries"
    j = ok(client, real_seed, merchant="freshmart.com")
    assert j["status"] == "rejected"
    o = order_of(db, j["order_id"])
    assert o.cart_json[0]["category"] == "electronics" and o.cart_json[0]["title"] == "Whole Milk 1L (Channel3)"
    assert "https://freshmart.com/p/p_milk" in o.page_urls


@pytest.mark.real_catalog_check
def test_checkout_must_match_the_cart_the_user_approved(client, db, real_seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    _channel3(monkeypatch)
    approved = [{"product_id": "p_milk", "qty": 1, "unit_price": "3.50", "merchant": "freshmart.com"}]

    def fresh_intent(cart):
        real_seed.intent = create_intent(db, user_id=real_seed.user.id, agent_id=real_seed.agent.id,
                                         request_text="Whole milk", approved_cart=cart)
        return real_seed.intent

    fresh_intent(approved)
    r = post(client, real_seed, _cart_body(real_seed, qty=2))
    assert r.status_code == 409 and r.json()["error"] == "not_what_you_approved"
    r = post(client, real_seed, _cart_body(real_seed, product_id="p_gift_card"))
    assert r.status_code == 409 and r.json()["error"] == "not_what_you_approved"
    fresh_intent([{**approved[0], "unit_price": "3.00"}])
    r = post(client, real_seed, _cart_body(real_seed))
    assert r.status_code == 409 and "more than the $3.00 you approved" in r.json()["reason"]
    fresh_intent([{**approved[0], "unit_price": "3.99"}])  # cheaper now: fine
    assert post(client, real_seed, _cart_body(real_seed)).status_code == 200


def test_one_order_per_purchase_request(client, db, seed, monkeypatch):
    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    first = ok(client, seed)
    assert first["status"] == "captured"
    r = post(client, seed, body(seed))
    assert r.status_code == 409 and r.json()["error"] == "intent_used"
    order_of(db, first["order_id"]).status = "failed"  # a technical failure frees the request
    db.commit()
    assert post(client, seed, body(seed)).status_code == 200


def test_intent_signature_covers_the_approved_cart(db, seed):
    from app.intents import verify_intent_signature

    cart = [{"product_id": "p_milk", "qty": 1, "unit_price": "3.50", "merchant": "freshmart.com"}]
    i = create_intent(db, user_id=seed.user.id, agent_id=seed.agent.id, request_text="milk", approved_cart=cart)
    assert verify_intent_signature(i) is True
    i.approved_cart = [{**cart[0], "qty": 5}]
    assert verify_intent_signature(i) is False
    assert verify_intent_signature(seed.intent) is True  # requests without a cart keep the old payload


def _hold_everything(monkeypatch):
    from app.policy import Decision

    real = core.decide

    def hold(*a, **k):
        d = real(*a, **k)
        return Decision("hold", ["Graph risk is high"]) if d.decision != "reject" else d
    monkeypatch.setattr(core, "decide", hold)


def test_pending_approvals_are_capped_per_agent(client, db, seed, monkeypatch):
    from app.pipeline.core import TOO_MANY_PENDING_REASON

    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    _hold_everything(monkeypatch)
    monkeypatch.setattr(core, "PENDING_APPROVALS_PER_AGENT", 2)
    statuses = []
    for _ in range(3):
        statuses.append(ok(client, seed)["status"])
        seed.intent = create_intent(db, user_id=seed.user.id, agent_id=seed.agent.id, request_text="Whole milk from freshmart")
    assert statuses == ["pending_approval", "pending_approval", "voided"]
    last = db.query(Order).filter_by(agent_id=seed.agent.id, status="voided").one()
    assert TOO_MANY_PENDING_REASON in last.reasons


def test_agent_daily_order_limit(client, db, seed, monkeypatch):
    from app import velocity

    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    monkeypatch.setattr(velocity, "AGENT_ORDERS_PER_DAY", 1)
    assert ok(client, seed)["status"] == "captured"
    seed.intent = create_intent(db, user_id=seed.user.id, agent_id=seed.agent.id, request_text="Whole milk from freshmart")
    r = post(client, seed, body(seed))
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


def test_failed_orders_dont_count_and_the_limit_is_configurable(client, db, seed, monkeypatch):
    from app import velocity

    clean_graph(monkeypatch)
    yes_hook(monkeypatch)
    monkeypatch.setenv("AGENT_ORDERS_PER_DAY", "1")
    paypal_service.mock_fail_next("authorize", PayPalError("INSTRUMENT_DECLINED"))
    assert ok(client, seed)["status"] == "failed"  # never reached PayPal: doesn't use the allowance
    seed.intent = create_intent(db, user_id=seed.user.id, agent_id=seed.agent.id, request_text="Whole milk from freshmart")
    assert ok(client, seed)["status"] == "captured"
    seed.intent = create_intent(db, user_id=seed.user.id, agent_id=seed.agent.id, request_text="Whole milk from freshmart")
    r = post(client, seed, body(seed))
    assert r.status_code == 429 and "limit of 1 orders" in r.json()["reason"]
    monkeypatch.setenv("AGENT_ORDERS_PER_DAY", "5")
    assert post(client, seed, body(seed)).status_code == 200
    assert velocity.AGENT_ORDERS_PER_DAY == 100
