"""Shared pytest fixtures for the intentlock service.

Advisory lock 912345 serialises DB creation + migration across parallel test
sessions.  Each test gets its own savepoint that is always rolled back.

Existing per-file fixtures (engine / db / client) override these because
pytest gives the closest-scope fixture precedence, so no existing test is
affected.
"""
from __future__ import annotations

import os
import subprocess
import sys
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

ADVISORY_LOCK_KEY = 912345


def _test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    try:
        from dotenv import dotenv_values
        base = (
            os.environ.get("DATABASE_URL")
            or dotenv_values(SERVICE_ROOT / ".env").get("DATABASE_URL")
        )
    except ImportError:
        base = os.environ.get("DATABASE_URL")
    if not base or base == "__FILL_ME__":
        pytest.fail("DATABASE_URL not configured; cannot locate intentlock_test")
    return make_url(base).set(database="intentlock_test").render_as_string(
        hide_password=False
    )


@pytest.fixture(scope="session")
def engine():
    """Session-scoped engine pointing at intentlock_test.

    Creates the DB if absent, runs alembic upgrade head under the advisory
    lock so parallel sessions don't race.
    """
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


@pytest.fixture()
def db(engine):
    """Function-scoped session wrapped in a savepoint; always rolled back."""
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
def wallet_key_b64():
    """A fresh Ed25519 private key in base64url, no padding."""
    from app.signing import b64url_encode

    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return b64url_encode(raw)


@pytest.fixture()
def client(db, wallet_key_b64, monkeypatch):
    """TestClient with the DB dependency overridden and wallet key set."""
    from app.config import settings
    from app.db import get_db
    from app.main import app as fastapi_app

    monkeypatch.setattr(settings, "INTENTLOCK_WALLET_PRIVATE_KEY", wallet_key_b64)

    def _override():
        yield db

    fastapi_app.dependency_overrides[get_db] = _override
    with TestClient(fastapi_app, raise_server_exceptions=True, headers=ADMIN) as c:
        yield c
    fastapi_app.dependency_overrides.pop(get_db, None)

ADMIN_KEY = "test-operator-key-0123456789"
ADMIN = {"X-Admin-Key": ADMIN_KEY}


@pytest.fixture(autouse=True)
def _operator_key(monkeypatch):
    """Operator-only routes are closed unless ADMIN_API_KEY is set; tests use this key."""
    from app.config import settings
    monkeypatch.setattr(settings, "ADMIN_API_KEY", ADMIN_KEY)



@pytest.fixture(autouse=True)
def _catalog_truth_passthrough(monkeypatch, request):
    """Checkout re-reads every line from Channel3 (app.product_truth). Tests use fixture products, so the
    lookup passes lines through unless a test marks itself @pytest.mark.real_catalog_check."""
    if request.node.get_closest_marker("real_catalog_check"):
        return
    from app.api import checkout

    def passthrough(merchant, lines, db=None):
        return merchant, [dict(l) for l in lines], []

    monkeypatch.setattr(checkout, "verify_cart", passthrough)

    from app.api import chats

    def same_offer(product, db=None):
        return {"merchant": product.get("merchant"), "price": product.get("price"), "currency": "USD",
                "url": product.get("url"), "title": product.get("title"), "category": product.get("category")}

    monkeypatch.setattr(chats, "current_offer", same_offer)


@pytest.fixture(autouse=True)
def _cart_review_passthrough(monkeypatch, request):
    """Chat checkout runs app.cart_review (Channel3 + Jev). Other tests get an "ok" review unless they mark
    themselves @pytest.mark.real_cart_review and fake Channel3/Jev themselves."""
    if request.node.get_closest_marker("real_cart_review"):
        return
    from app.api import chats

    def ok(request_text, lines, rule_issues):
        status = "block" if rule_issues else "pass"
        return {"decision": "block" if rule_issues else "ok",
                "checks": [{"key": "rules", "label": "Within your spending rules", "status": status,
                            "detail": " ".join(rule_issues)}]}

    monkeypatch.setattr(chats, "review_cart", ok)


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """Never send real email from tests (the local .env may hold a real Resend key). Tests that check email
    set RESEND_API_KEY themselves."""
    from app.config import settings
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "WEB_ORIGIN", "http://localhost:3000")


@pytest.fixture(autouse=True)
def _channel3_guards(monkeypatch):
    """Channel3's daily budget lives in Postgres; unit tests count in memory instead, and the circuit breaker
    starts closed. Tests of the budget itself call the real spend_credit."""
    from app import channel3

    channel3.reset_guards()
    calls = {"n": 0}

    def spend(kind):
        calls["n"] += 1
        return calls["n"]

    monkeypatch.setattr(channel3, "spend_credit", spend)
    monkeypatch.setattr(channel3, "_sleep", lambda s: None)


def buyer_fields() -> dict:
    """User columns a buyer needs before any order of theirs can be paid: a verified email and a shipping address."""
    import uuid

    from app.signing import utcnow

    return {
        "email": f"buyer-{uuid.uuid4().hex[:12]}@example.com",
        "email_verified_at": utcnow(),
        "shipping_address": {"name": "Priya Test", "line1": "1 Main St", "city": "Springfield",
                             "region": "IL", "postal_code": "62701", "country": "US"},
    }


def prepare_capturable(db, order, *, category: str = "groceries"):
    """Give an existing order everything the 32 payment checks look for, so that it can be paid."""
    from datetime import timedelta
    from decimal import Decimal

    from app.mandates import create_mandate, select_mandate_for_agent
    from app.models import Check, User
    from app.pipeline.steps import record_check
    from app.signing import utcnow

    user = db.get(User, order.user_id)
    for key, value in buyer_fields().items():
        if getattr(user, key) is None:
            setattr(user, key, value)
    if select_mandate_for_agent(db, order.agent_id, order.merchant) is None:
        create_mandate(db, {
            "agent_id": order.agent_id, "categories": [category], "merchants": [order.merchant],
            "budget_amount": "4000.00", "budget_period": "week", "currency": order.currency,
            "starts_at": utcnow() - timedelta(days=1), "expires_at": utcnow() + timedelta(days=30),
        })
    if not order.cart_json:
        order.cart_json = [{"product_id": "p_item", "title": "Item", "qty": 1,
                            "unit_price": str(Decimal(str(order.total)).quantize(Decimal("0.01"))),
                            "currency": order.currency, "category": category}]
    order.page_urls = order.page_urls or []
    suffix = order.id[-8:]
    order.paypal_order_id = order.paypal_order_id or "MOCK-O-" + suffix
    order.authorization_id = order.authorization_id or "MOCK-A-" + suffix
    have = {c.step for c in db.query(Check).filter(Check.order_id == order.id)}
    rows = (
        ("verify_agent", {"result": "pass", "reason": "ok"}, None),
        ("check_mandate", {"result": "pass", "reason": "ok"}, None),
        ("scan_injection", {"detected": False, "confidence": 0.99}, 0.99),
        ("intent_diff", {"items": [{"explained": "yes"}], "price_anomaly": False}, None),
        ("graph_risk", {"score": 5}, 5),
    )
    for step, details, score in rows:
        if step not in have:
            record_check(db, order.id, step, "pass", details, 1, score)
    db.flush()
    return order


def make_capturable_order(db, *, status: str = "pending_approval", total: str = "3.50", merchant: str = "freshmart",
                          expires_in_min: int = 30, approval: bool = True):
    """A whole buyer, agent, rule, signed request and order that passes every payment check."""
    from datetime import timedelta
    from decimal import Decimal
    from types import SimpleNamespace

    from app.crypto.keys import generate_keypair_b64
    from app.ids import new_id
    from app.intents import create_intent
    from app.models import Agent, Approval, Order, User
    from app.paypal import service as paypal_service
    from app.signing import utcnow

    _priv, pub = generate_keypair_b64()
    user = User(id=new_id("usr"), name="Tester", **buyer_fields())
    db.add(user)
    db.flush()
    agent = Agent(id=new_id("agt"), user_id=user.id, name="shopper", public_key=pub, device_id="dev1", verified=True)
    db.add(agent)
    db.flush()
    intent = create_intent(db, user_id=user.id, agent_id=agent.id, request_text="buy groceries")
    oid = new_id("ord")
    held = status == "pending_approval"
    order = Order(
        id=oid, intent_id=intent.id, agent_id=agent.id, user_id=user.id, merchant=merchant,
        cart_json=[], total=Decimal(total), currency="USD", status=status,
        decision="hold" if held else None, reasons=["needs review"] if held else None,
    )
    db.add(order)
    db.flush()
    prepare_capturable(db, order)
    appr = None
    if approval and held:
        now = utcnow()
        appr = Approval(id=new_id("apr"), order_id=oid, requested_at=now,
                        expires_at=now + timedelta(minutes=expires_in_min))
        db.add(appr)
        db.flush()
    with paypal_service._LOCK:
        paypal_service._AUTH[order.authorization_id] = "authorized"
    return SimpleNamespace(user=user, agent=agent, intent=intent, order=order, approval=appr)
