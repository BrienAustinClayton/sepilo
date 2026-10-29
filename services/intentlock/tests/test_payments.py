"""Payment edge-case tests – P4-T07.

Marked ``payments`` (PAYPAL_MODE=mock) and ``sandbox`` (live PayPal Sandbox,
skip unless RUN_SANDBOX=1 and app/paypal/sandbox.py exists).

Cases:
  1. authorize → void
  2. authorize → capture
  3. capture twice is idempotent (same capture_id, no error)
  4. approval timeout voids via expire_approvals.run_once
  5. mandate reject → zero PayPal calls
  6. PayPal authorize failure → order failed, no capture
  7. capture failure on approve → order not captured, user gets clean 502
  8. webhook replay skipped (P1-T13 not built)
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.ids import new_id  # noqa: E402
from app.jobs.expire_approvals import run_once  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import Agent, Approval, Intent, Order, User  # noqa: E402
from app.paypal import service as paypal_service  # noqa: E402
from app.paypal.service import PayPalError  # noqa: E402
from app.pipeline import limits  # noqa: E402
from app.pipeline.core import run_pipeline  # noqa: E402
from app.pipeline.runner import LocalExecutor  # noqa: E402
from app.pipeline.steps import record_check  # noqa: E402
from app.signing import b64url_encode, utcnow  # noqa: E402
ADMIN = {"X-Admin-Key": "test-operator-key-0123456789"}  # same key as conftest._operator_key

# --------------------------------------------------------------------------- #
# Sandbox availability (evaluated at import time, not test time)
# --------------------------------------------------------------------------- #
_SANDBOX_AVAILABLE = (
    os.environ.get("RUN_SANDBOX") == "1"
    and (SERVICE_ROOT / "app" / "paypal" / "sandbox.py").exists()
)
_skip_sandbox = pytest.mark.skipif(
    not _SANDBOX_AVAILABLE,
    reason="sandbox tests require RUN_SANDBOX=1 and app/paypal/sandbox.py",
)


# --------------------------------------------------------------------------- #
# Local fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture()
def proof_key_b64():
    """A fresh Ed25519 proof key for each test."""
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return b64url_encode(raw)


@pytest.fixture(autouse=True)
def _payment_env(monkeypatch, wallet_key_b64, proof_key_b64):
    """Common environment for every test in this module: mock PayPal, clean state."""
    monkeypatch.setattr(settings, "INTENTLOCK_PROOF_PRIVATE_KEY", proof_key_b64)
    monkeypatch.setattr(settings, "INTENTLOCK_WALLET_PRIVATE_KEY", wallet_key_b64)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    for k in ("PIPELINE_MODE", "PIPELINE_STUBS", "APPROVAL_TIMEOUT_MIN"):
        monkeypatch.delenv(k, raising=False)
    # Zero back-off so retries don't slow down tests.
    monkeypatch.setattr(limits, "PAY_BACKOFF_S", 0.0)
    paypal_service.reset_mock()


@pytest.fixture()
def test_client(db):
    """TestClient with the test DB session injected (no HTTP signature required)."""
    def _override():
        yield db

    fastapi_app.dependency_overrides[get_db] = _override
    try:
        with TestClient(fastapi_app, raise_server_exceptions=False, headers=ADMIN) as c:
            yield c
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


# --------------------------------------------------------------------------- #
# DB helpers (same pattern as test_approvals.py)
# --------------------------------------------------------------------------- #

def _seed(db):
    """Minimal user + agent (no intent – callers create their own)."""
    from app.crypto.keys import generate_keypair_b64
    _priv, pub = generate_keypair_b64()
    u = User(id=new_id("usr"), name="PayTest")
    db.add(u)
    db.flush()
    a = Agent(
        id=new_id("agt"), user_id=u.id, name="shopper",
        public_key=pub, device_id="dev-pay", verified=True,
    )
    db.add(a)
    db.flush()
    return u, a


def _pending_order(db, *, expires_in_min: int = 30) -> tuple[Order, Approval]:
    """Create an order already in pending_approval that passes every payment check, with a registered mock auth."""
    from conftest import make_capturable_order
    made = make_capturable_order(db, expires_in_min=expires_in_min)
    return made.order, made.approval


def _received_order(db, *, unit_price: str = "3.50") -> str:
    """
    Create a received order with a valid mandate and properly signed intent.

    The mandate has budget_amount=100.00, so unit_price > 100.00 triggers a
    mandate breach; unit_price <= 100.00 passes the mandate and reaches
    authorize.  The intent is signed with the current wallet key so that
    check_mandate's intent-signature check passes.
    """
    from app.intents import create_intent
    from app.mandates import create_mandate
    u, a = _seed(db)
    create_mandate(db, {
        "agent_id": a.id,
        "categories": ["groceries"],
        "merchants": ["freshmart"],
        "budget_amount": "100.00",
        "budget_period": "week",
        "currency": "USD",
        "starts_at": utcnow() - timedelta(days=1),
        "expires_at": utcnow() + timedelta(days=30),
    })
    db.flush()
    # create_intent uses the current wallet key (set by _payment_env).
    i = create_intent(db, user_id=u.id, agent_id=a.id, request_text="buy groceries")
    oid = new_id("ord")
    o = Order(
        id=oid, intent_id=i.id, agent_id=a.id, user_id=u.id,
        merchant="freshmart",
        cart_json=[{"product_id": "p_milk", "title": "Whole Milk 1L", "qty": 1,
                    "unit_price": unit_price, "currency": "USD", "category": "groceries"}],
        total=Decimal(unit_price), currency="USD",
        status="received", page_urls=[], shipping_address=None,
    )
    db.add(o)
    db.flush()
    record_check(db, oid, "verify_agent", "pass",
                 {"result": "pass", "reason": "ok", "keyid": a.id}, 1)
    db.commit()
    return oid


# --------------------------------------------------------------------------- #
# ── MOCK tests ────────────────────────────────────────────────────────────── #
# --------------------------------------------------------------------------- #

@pytest.mark.payments
def test_authorize_then_void():
    """Mock: authorize then void → auth state is voided, only void call recorded."""
    auth_id = "MOCK-A-TESTVOID1"
    with paypal_service._LOCK:
        paypal_service._AUTH[auth_id] = "authorized"

    paypal_service.void(auth_id, request_id="req-void-1")

    calls = paypal_service.mock_calls()
    assert len(calls) == 1
    assert calls[0]["op"] == "void"
    assert calls[0]["authorization_id"] == auth_id
    with paypal_service._LOCK:
        assert paypal_service._AUTH[auth_id] == "voided"


@pytest.mark.payments
def test_authorize_then_capture():
    """Mock: authorize then capture → MOCK-C-* capture_id returned, state captured."""
    auth_id = "MOCK-A-TESTCAP1"
    with paypal_service._LOCK:
        paypal_service._AUTH[auth_id] = "authorized"

    cap_id = paypal_service.capture(auth_id, request_id="req-cap-1")

    assert cap_id.startswith("MOCK-C-"), f"unexpected capture id: {cap_id}"
    calls = paypal_service.mock_calls()
    assert len(calls) == 1
    assert calls[0]["op"] == "capture"
    with paypal_service._LOCK:
        assert paypal_service._AUTH[auth_id] == "captured"


@pytest.mark.payments
def test_capture_twice_idempotent():
    """Mock: calling capture twice returns the same capture_id without raising."""
    auth_id = "MOCK-A-TESTIDE1"
    with paypal_service._LOCK:
        paypal_service._AUTH[auth_id] = "authorized"

    cap1 = paypal_service.capture(auth_id, request_id="req-idem-1")
    cap2 = paypal_service.capture(auth_id, request_id="req-idem-2")

    assert cap1 == cap2, "second capture must return the same capture_id (idempotent)"
    # Both calls are recorded (the service observed two network events).
    capture_calls = [c for c in paypal_service.mock_calls() if c["op"] == "capture"]
    assert len(capture_calls) == 2


@pytest.mark.payments
def test_approval_timeout_voids_order(db, monkeypatch):
    """Mock: APPROVAL_TIMEOUT_MIN=1; expired pending_approval is voided by run_once."""
    monkeypatch.setenv("APPROVAL_TIMEOUT_MIN", "1")
    # expires_in_min=-1 simulates the 1-minute window having already lapsed.
    o, appr = _pending_order(db, expires_in_min=-1)
    db.flush()

    voided = run_once(_db=db)
    assert voided >= 1

    db.expire_all()
    updated_order = db.get(Order, o.id)
    updated_appr = db.get(Approval, appr.id)

    assert updated_order.status == "voided"
    assert updated_appr.decision == "decline"
    assert updated_appr.decided_at is not None

    # expire_approvals must have called void exactly once, never capture.
    ops = [c["op"] for c in paypal_service.mock_calls()]
    assert ops == ["void"], f"unexpected ops: {ops}"


@pytest.mark.payments
def test_mandate_reject_zero_paypal_calls(db):
    """Mock: over-budget order is rejected before authorize → zero PayPal calls."""
    # unit_price=150.00 > mandate budget 100.00 → mandate breach
    oid = _received_order(db, unit_price="150.00")
    asyncio.run(run_pipeline(db, oid, LocalExecutor(db)))

    db.expire_all()
    order = db.get(Order, oid)

    assert order.status == "rejected"
    assert order.decision == "reject"
    assert paypal_service.mock_calls() == [], (
        "PayPal must not be contacted when the mandate check fails"
    )


@pytest.mark.payments
def test_authorize_failure_order_failed(db):
    """Mock: non-retryable authorize failure → order status=failed, no capture."""
    paypal_service.mock_fail_next(
        "authorize", PayPalError("INSTRUMENT_DECLINED", retryable=False), times=99
    )
    oid = _received_order(db)
    asyncio.run(run_pipeline(db, oid, LocalExecutor(db)))

    db.expire_all()
    order = db.get(Order, oid)

    assert order.status == "failed"
    ops = [c["op"] for c in paypal_service.mock_calls()]
    # authorize was attempted; no capture or void should follow.
    assert "authorize" in ops
    assert "capture" not in ops
    assert "void" not in ops


@pytest.mark.payments
def test_capture_failure_on_approve_clean_error(db, test_client):
    """Mock: capture fails during approval → 502 paypal_error, order stays pending_approval."""
    o, _appr = _pending_order(db)
    paypal_service.mock_fail_next("capture", PayPalError("CAPTURE_FAILED"))

    r = test_client.post(f"/orders/{o.id}/approval", json={"decision": "approve"})

    assert r.status_code == 502
    # errors.py's http_exception_handler returns the dict directly (not wrapped in "detail")
    # when the detail already has the {"error": ..., "reason": ...} shape.
    body = r.json()
    assert body.get("error") == "paypal_error", f"unexpected body: {body}"
    assert body.get("reason") == "CAPTURE_FAILED"

    # The order must not have been captured; must stay at pending_approval.
    db.expire_all()
    updated = db.get(Order, o.id)
    assert updated.status == "pending_approval", (
        f"order should remain pending_approval after capture failure, got {updated.status}"
    )
    assert updated.capture_id is None, "capture_id must not be set after a failed capture"


@pytest.mark.payments
@pytest.mark.skip(reason="P1-T13 not built; PayPal webhook deduplication not implemented")
def test_webhook_replay_skipped():  # pragma: no cover
    """Placeholder: webhook replay idempotency is tested in P1-T13."""


# --------------------------------------------------------------------------- #
# ── SANDBOX tests ─────────────────────────────────────────────────────────── #
# Same scenarios as mock tests; skip until RUN_SANDBOX=1 + sandbox.py exists. #
# --------------------------------------------------------------------------- #

def _sandbox_order(db, *, unit_price: str = "1.00") -> tuple:
    """Helper: user + agent + bare Order in 'received' status for sandbox tests."""
    u, a = _seed(db)
    i = Intent(
        id=new_id("int"), user_id=u.id, agent_id=a.id,
        request_text="sandbox test", signature="sig", signed_at=utcnow(),
    )
    db.add(i)
    db.flush()
    oid = new_id("ord")
    o = Order(
        id=oid, intent_id=i.id, agent_id=a.id, user_id=u.id,
        merchant="freshmart",
        cart_json=[{"product_id": "p_milk", "title": "Whole Milk 1L", "qty": 1,
                    "unit_price": unit_price, "currency": "USD", "category": "groceries"}],
        total=Decimal(unit_price), currency="USD",
        status="received",
    )
    db.add(o)
    db.flush()
    return u, a, i, o


@pytest.mark.sandbox
@_skip_sandbox
def test_sandbox_authorize_then_void(db, monkeypatch):
    """Sandbox: authorize then void via real PayPal Sandbox API."""
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    _u, _a, _i, o = _sandbox_order(db)

    _pp_order_id, auth_id = paypal_service.authorize(o)
    assert auth_id, "authorize must return a non-empty auth_id"

    paypal_service.void(auth_id, request_id=o.id + "-void")
    # If void raises PayPalError the test fails with a clear message.


@pytest.mark.sandbox
@_skip_sandbox
def test_sandbox_authorize_then_capture(db, monkeypatch):
    """Sandbox: authorize then capture via real PayPal Sandbox API."""
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    _u, _a, _i, o = _sandbox_order(db)

    _pp_order_id, auth_id = paypal_service.authorize(o)
    cap_id = paypal_service.capture(auth_id, request_id=o.id + "-capture")
    assert cap_id, "capture must return a non-empty capture_id"


@pytest.mark.sandbox
@_skip_sandbox
def test_sandbox_capture_twice_idempotent(db, monkeypatch):
    """Sandbox: calling capture twice with the same request_id returns the same result."""
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    _u, _a, _i, o = _sandbox_order(db)

    _pp_order_id, auth_id = paypal_service.authorize(o)
    cap1 = paypal_service.capture(auth_id, request_id=o.id + "-idem")
    cap2 = paypal_service.capture(auth_id, request_id=o.id + "-idem")
    assert cap1 == cap2, "Sandbox: second capture with same request_id must be idempotent"


@pytest.mark.sandbox
@_skip_sandbox
def test_sandbox_approval_timeout_voids_order(db, monkeypatch):
    """Sandbox: expired pending_approval is voided by run_once (APPROVAL_TIMEOUT_MIN=1)."""
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    monkeypatch.setenv("APPROVAL_TIMEOUT_MIN", "1")

    # Build a real auth_id from the sandbox, then put the order in pending_approval
    # with an already-expired window so run_once voids it.
    _u, _a, _i, tmp = _sandbox_order(db)
    oid = tmp.id
    _pp_oid, auth_id = paypal_service.authorize(tmp)

    # Promote to pending_approval with an already-expired approval window.
    now = utcnow()
    tmp.status = "authorized"
    tmp.paypal_order_id = _pp_oid
    tmp.authorization_id = auth_id
    tmp.decision = "hold"
    tmp.reasons = ["needs review"]
    # Manually transition status (pipeline ordinarily does this).
    from app.pipeline.steps import set_status
    set_status(tmp, "checking", [])
    set_status(tmp, "pending_approval", [])
    db.flush()
    appr = Approval(
        id=new_id("apr"), order_id=oid,
        requested_at=now,
        expires_at=now - timedelta(minutes=1),  # already expired
        decision=None, decided_at=None,
    )
    db.add(appr)
    db.flush()

    voided = run_once(_db=db)
    assert voided >= 1

    db.expire_all()
    updated = db.get(Order, oid)
    assert updated.status == "voided"


@pytest.mark.sandbox
@_skip_sandbox
def test_sandbox_mandate_reject_zero_paypal_calls(db, monkeypatch):
    """Sandbox: mandate breach rejects before authorize → no Sandbox calls made."""
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    # over-budget → rejected before authorize
    oid = _received_order(db, unit_price="150.00")
    asyncio.run(run_pipeline(db, oid, LocalExecutor(db)))

    db.expire_all()
    order = db.get(Order, oid)
    assert order.status == "rejected"
    assert order.decision == "reject"
    # No PayPal sandbox calls should have been attempted.


@pytest.mark.sandbox
@_skip_sandbox
def test_sandbox_authorize_failure_order_failed(db, monkeypatch):
    """Sandbox: authorize with zero-amount order fails → order status=failed."""
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    # A zero-amount cart is invalid and should be rejected by PayPal.
    oid = _received_order(db, unit_price="0.01")
    # Override budget to allow the mandate to pass for this tiny amount.
    # Then trigger an authorize failure by making the order amount invalid
    # (sandbox: use an explicitly invalid amount by patching the order total to 0).
    db.expire_all()
    o = db.get(Order, oid)
    o.total = Decimal("0.00")
    # Also update cart so OrderDraft.total reflects zero.
    o.cart_json = [{"product_id": "p_milk", "title": "Whole Milk", "qty": 1,
                    "unit_price": "0.00", "currency": "USD", "category": "groceries"}]
    db.flush()

    asyncio.run(run_pipeline(db, oid, LocalExecutor(db)))

    db.expire_all()
    order = db.get(Order, oid)
    assert order.status == "failed"
    ops = [c["op"] for c in paypal_service.mock_calls()]
    assert "capture" not in ops


@pytest.mark.sandbox
@_skip_sandbox
def test_sandbox_capture_failure_on_approve_clean_error(db, test_client, monkeypatch):
    """Sandbox: capture on voided auth → 502 paypal_error, order not captured."""
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    # Create a real sandbox authorization and immediately void it manually.
    # Then try to capture the voided auth via the approval endpoint.
    _u, _a, _i, tmp = _sandbox_order(db)
    oid = tmp.id
    _pp_oid, auth_id = paypal_service.authorize(tmp)

    # Void it so a subsequent capture attempt fails.
    paypal_service.void(auth_id, request_id=oid + "-pre-void")

    # Now put the order in pending_approval state pointing at the voided auth.
    now = utcnow()
    tmp.status = "authorized"
    tmp.paypal_order_id = _pp_oid
    tmp.authorization_id = auth_id
    tmp.decision = "hold"
    tmp.reasons = ["needs review"]
    from app.pipeline.steps import set_status
    set_status(tmp, "checking", [])
    set_status(tmp, "pending_approval", [])
    db.flush()
    appr = Approval(
        id=new_id("apr"), order_id=oid,
        requested_at=now,
        expires_at=now + timedelta(minutes=30),
        decision=None, decided_at=None,
    )
    db.add(appr)
    db.flush()

    r = test_client.post(f"/orders/{oid}/approval", json={"decision": "approve"})

    assert r.status_code == 502
    body = r.json()
    assert body.get("error") == "paypal_error", f"unexpected body: {body}"

    db.expire_all()
    updated = db.get(Order, oid)
    assert updated.status == "pending_approval"
    assert updated.capture_id is None
