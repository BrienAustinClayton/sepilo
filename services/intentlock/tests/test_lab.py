"""Tests for P4-T04 (lab part): POST /lab/{scenario} through the real verify + pipeline path."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))

from conftest import buyer_fields  # noqa: E402
from app.api import lab as lab_mod  # noqa: E402
from app.checks import intent_diff as intent_diff_mod  # noqa: E402
from app.crypto.keys import generate_keypair_b64  # noqa: E402
from app.crypto.vector import VECTOR_PUBLIC_KEY  # noqa: E402
from app.jev import Answer  # noqa: E402
from app.mandates import create_mandate  # noqa: E402
from app.models import Agent, Check, Order, User  # noqa: E402
from app.paypal import service as paypal_service  # noqa: E402
from app.signing import utcnow  # noqa: E402

SCENARIOS = {
    "normal": ("capture", "captured"),
    "hidden_gift_card": ("void", "voided"),
    "wrong_variant": ("hold", "pending_approval"),
    "overpriced_merchant": ("hold", "pending_approval"),
    "bot_farm": ("void", "voided"),
    "revoked_agent": ("reject", "rejected"),
}
PRIYA = "usr_demo_priya"


def _upsert_agent(db, agent_id, public_key, device_id, *, verified, revoked=False):
    a = db.get(Agent, agent_id)
    if a is None:
        a = Agent(id=agent_id, user_id=PRIYA, name=agent_id, public_key=public_key,
                  device_id=device_id, verified=verified)
        db.add(a)
    a.public_key, a.device_id, a.verified = public_key, device_id, verified
    a.revoked_at = utcnow() if revoked else None
    db.flush()
    return a


def _mandate(db, agent_id, cats, merchants, budget):
    from app.models import Mandate

    for m in db.execute(select(Mandate).where(Mandate.agent_id == agent_id)).scalars():
        m.revoked_at = utcnow()
    db.flush()
    create_mandate(db, {
        "agent_id": agent_id, "categories": cats, "merchants": merchants,
        "budget_amount": budget, "budget_period": "week", "currency": "USD",
        "starts_at": utcnow() - timedelta(days=1), "expires_at": utcnow() + timedelta(days=30),
    })


@pytest.fixture()
def lab_env(db, client, monkeypatch, tmp_path):
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    for k in ("PIPELINE_MODE", "PIPELINE_STUBS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("INTENTLOCK_GRAPH_FLAGS_PATH", str(tmp_path / "flags.json"))
    # seed-only graph: no connection to the real database from the graph package
    monkeypatch.setattr("intentlock_graph.risk._default_db_session", lambda: None)
    paypal_service.reset_mock()
    # clear any committed orders for the lab agents so budget and graph start clean
    priv, pub = generate_keypair_b64()
    monkeypatch.setenv("AGENT_PRIVATE_KEY", priv)
    if db.get(User, PRIYA) is None:
        db.add(User(id=PRIYA, name="Priya", paypal_payment_token="tok_test", **buyer_fields()))
        db.flush()
    _upsert_agent(db, "agt_demo_shopper", pub, "dev_priya_macbook", verified=True)
    _upsert_agent(db, "agt_lab_revoked", VECTOR_PUBLIC_KEY, "dev_priya_macbook", verified=True, revoked=True)
    for i in range(1, 13):
        _upsert_agent(db, f"agt_lab_bot_{i:02d}", VECTOR_PUBLIC_KEY,
                      "dev_shared_bot_01" if i <= 6 else "dev_shared_bot_02", verified=False)
    _mandate(db, "agt_demo_shopper", ["groceries", "electronics_accessories", "gift_cards"],
             ["freshmart", "gadgethub", "dealsdaily"], "200.00")
    _mandate(db, "agt_lab_bot_07", ["electronics_accessories"], ["dealsdaily"], "100.00")
    db.flush()
    return client


@pytest.fixture()
def fake_jev(monkeypatch):
    """Deterministic Jev: uncertain lines are explained, except the 2 m cable (variant mismatch)."""
    calls = []

    def fake(state, questions, step, demo=False, **kw):
        calls.append(step)
        bad = '"variant": "2 m"' in (state if isinstance(state, str) else json.dumps(state, default=str))
        out = {}
        for key, q in questions.items():
            if q["type"] == "noul":
                out[key] = Answer(type="noul", noul=0.1 if bad else 0.9, engine="jev")
            else:
                out[key] = Answer(type="choice", choice="variant_mismatch" if bad else "none",
                                  confidence=0.9, engine="jev")
        return out

    monkeypatch.setattr(intent_diff_mod, "decide", fake)
    return calls


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_scenario_reaches_expected_decision(lab_env, fake_jev, scenario):
    expected, status = SCENARIOS[scenario]
    r = lab_env.post(f"/lab/{scenario}", json={"user_id": PRIYA})
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"order_id", "order", "scenario", "expected_decision", "actual_decision", "status", "reasons"}
    assert j["order"]["id"] == j["order_id"] and j["order"]["checks"]
    assert j["scenario"] == scenario
    assert j["expected_decision"] == expected
    assert j["actual_decision"] == expected, j
    assert j["status"] == status
    assert j["order_id"].startswith("ord_")


def test_revoked_agent_has_order_fail_check_and_no_paypal_calls(lab_env, db):
    j = lab_env.post("/lab/revoked_agent", json={"user_id": PRIYA}).json()
    order = db.get(Order, j["order_id"])
    assert order is not None and order.agent_id == "agt_lab_revoked"
    assert order.authorization_id is None and order.paypal_order_id is None
    rows = {c.step: c for c in db.execute(select(Check).where(Check.order_id == order.id)).scalars()}
    assert rows["verify_agent"].result == "fail"
    assert rows["verify_agent"].details_json["reason"] == "revoked"
    assert rows["authorize_payment"].result == "skipped"
    assert rows["capture_or_void"].result == "skipped"
    assert j["reasons"]


def test_lab_signs_with_scenario_agent_key_and_verifies(lab_env, fake_jev, db):
    j = lab_env.post("/lab/normal", json={"user_id": PRIYA}).json()
    row = db.execute(select(Check).where(Check.order_id == j["order_id"], Check.step == "verify_agent")).scalar_one()
    assert row.result == "pass" and row.details_json["keyid"] == "agt_demo_shopper"
    j = lab_env.post("/lab/bot_farm", json={}).json()  # body optional, default user
    row = db.execute(select(Check).where(Check.order_id == j["order_id"], Check.step == "verify_agent")).scalar_one()
    assert row.result == "pass" and row.details_json["keyid"] == "agt_lab_bot_07"


def test_wrong_key_for_demo_agent_fails_verification(lab_env, db, monkeypatch):
    other_priv, _ = generate_keypair_b64()
    monkeypatch.setenv("AGENT_PRIVATE_KEY", other_priv)
    j = lab_env.post("/lab/normal", json={"user_id": PRIYA}).json()
    assert j["actual_decision"] == "reject" and j["status"] == "rejected"
    row = db.execute(select(Check).where(Check.order_id == j["order_id"], Check.step == "verify_agent")).scalar_one()
    assert row.result == "fail" and row.details_json["reason"] == "bad_signature"


def test_fixture_pages_are_absolute_and_only_lab_allows_fixtures(lab_env, fake_jev, db, monkeypatch):
    seen = []
    from app.pipeline import runner

    real = runner.run_checkout

    async def spy(db_, order_id, *a, **kw):
        seen.append(kw.get("allow_fixtures"))
        return await real(db_, order_id, *a, **kw)

    monkeypatch.setattr(lab_mod, "run_checkout", spy)
    j = lab_env.post("/lab/hidden_gift_card", json={"user_id": PRIYA}).json()
    assert seen == [True]
    order = db.get(Order, j["order_id"])
    assert order.page_urls and all(Path(p).is_absolute() and Path(p).exists() for p in order.page_urls)


def test_unknown_scenario_404(lab_env):
    r = lab_env.post("/lab/nope", json={"user_id": PRIYA})
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_caller_cannot_pick_the_lab_user(lab_env, db):
    r = lab_env.post("/lab/normal", json={"user_id": "usr_someone_else"})
    assert r.status_code == 200
    assert db.get(Order, r.json()["order_id"]).user_id == PRIYA


def test_lab_routes_closed_without_operator_key_or_session(lab_env):
    from fastapi.testclient import TestClient
    from app.main import app

    anon = TestClient(app)
    assert anon.post("/lab/normal").status_code == 401
    assert anon.post("/lab/reset").status_code == 401
    assert anon.post("/me/lab/normal").status_code == 401
    assert anon.post("/me/lab/reset").status_code == 401


def test_lab_reset_keeps_other_users_orders(lab_env, db):
    from decimal import Decimal
    from app.ids import new_id
    from app.models import Agent, Intent, User
    from app.intents import new_signed_intent

    u = User(id=new_id("usr"), name="Other")
    db.add(u)
    db.flush()
    a = Agent(id=new_id("agt"), user_id=u.id, name="x", public_key="k", device_id="d", verified=True)
    db.add(a)
    db.flush()
    i = new_signed_intent(user_id=u.id, agent_id=a.id, request_text="socks")
    db.add(i)
    db.flush()
    other = Order(id=new_id("ord"), intent_id=i.id, agent_id=a.id, user_id=u.id, merchant="m",
                  cart_json=[], total=Decimal("1.00"), currency="USD", status="captured")
    db.add(other)
    db.commit()
    lab_env.post("/lab/revoked_agent")
    assert lab_env.post("/lab/reset").status_code == 200
    db.expire_all()
    assert db.get(Order, other.id) is not None


def test_lab_reset_deletes_data(lab_env, db):
    """POST /lab/reset deletes orders (and checks etc.) and returns counts."""
    # revoked_agent scenario reaches the pipeline but is rejected before PayPal
    r = lab_env.post("/lab/revoked_agent", json={"user_id": PRIYA})
    assert r.status_code == 200
    order_id = r.json()["order_id"]
    assert db.get(Order, order_id) is not None

    r2 = lab_env.post("/lab/reset")
    assert r2.status_code == 200
    j = r2.json()
    assert j["ok"] is True
    assert "orders" in j["deleted"]
    assert j["deleted"]["orders"] >= 1

    db.expire_all()
    assert db.get(Order, order_id) is None


def test_lab_reset_disabled_returns_403(lab_env, monkeypatch):
    """When LAB_RESET_ENABLED=0, POST /lab/reset returns 403."""
    monkeypatch.setenv("LAB_RESET_ENABLED", "0")
    r = lab_env.post("/lab/reset")
    assert r.status_code == 403
    j = r.json()
    assert j.get("error") == "lab_reset_disabled"


@pytest.mark.llm
def test_live_all_six_with_real_jev(lab_env, request):
    if "llm" not in (request.config.getoption("-m") or ""):
        pytest.skip("live test; run with -m llm")
    from app.config import settings

    if not settings.LLM_SMART_API_KEY or settings.LLM_SMART_API_KEY == "__FILL_ME__":
        pytest.skip("LLM_SMART_API_KEY not configured")
    got = {}
    for s in SCENARIOS:
        got[s] = lab_env.post(f"/lab/{s}", json={"user_id": PRIYA}).json()["actual_decision"]
    assert got == {s: SCENARIOS[s][0] for s in SCENARIOS}
