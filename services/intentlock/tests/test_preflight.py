"""The 32 payment checks, the payment notice email, and how the pipeline and approvals use them."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from conftest import make_capturable_order
from app import notify, preflight
from app.config import settings
from app.ids import new_id
from app.models import Check, Order, User
from app.paypal import service as paypal_service
from app.pipeline import core
from app.preflight import run_preflight
from app.signing import utcnow


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    paypal_service.reset_mock()


@pytest.fixture()
def made(db, client):
    return make_capturable_order(db, status="checking", approval=False)


def by_id(result, cid):
    return next(c for c in result["checks"] if c["id"] == cid)


def set_row(db, order, step, result, details=None, score=None):
    row = db.execute(select(Check).where(Check.order_id == order.id, Check.step == step)).scalar_one()
    row.result = result
    if details is not None:
        row.details_json = details
    if score is not None:
        row.score = score
    db.flush()


def test_clean_order_passes_all_32_and_snapshots_the_address(db, made):
    r = run_preflight(db, made.order, user_approved=False)
    assert r["passed"] is True and r["failed"] == []
    assert len(r["checks"]) == 32
    assert [c["id"] for c in r["checks"]] == [f"P{n:02d}" for n in range(1, 33)]
    assert all(c["status"] == "pass" for c in r["checks"])
    assert made.order.shipping_address == made.user.shipping_address


def test_no_shipping_address_fails_and_the_email_is_not_sent(db, made, monkeypatch):
    sent = []
    monkeypatch.setattr(preflight, "send_payment_notice", lambda u, o: sent.append(o.id) or True)
    made.user.shipping_address = None
    r = run_preflight(db, made.order, user_approved=False)
    assert r["passed"] is False
    assert "Shipping address on file" in r["failed"]
    assert by_id(r, "P32")["detail"] == "not_sent" and "Payment notice emailed to you" not in r["failed"]
    assert sent == [] and made.order.shipping_address is None


def test_incomplete_or_foreign_address_fails(db, made):
    made.user.shipping_address = {"name": "A", "line1": "1 St", "city": "X", "postal_code": "1", "country": "USA"}
    assert "Shipping address is complete" in run_preflight(db, made.order, user_approved=False)["failed"]
    made.user.shipping_address = {"name": "A", "line1": "1 St", "city": "X", "postal_code": "1", "country": "GB"}
    made.user.country = "US"
    assert "Shipping country matches your country" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_unverified_email_fails(db, made):
    made.user.email_verified_at = None
    assert "Verified email on file" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_revoked_agent_fails(db, made):
    made.agent.revoked_at = utcnow()
    r = run_preflight(db, made.order, user_approved=False)
    assert r["passed"] is False and "Agent is active" in r["failed"]


def test_agent_of_another_user_fails(db, made):
    other = User(id=new_id("usr"), name="Other")
    db.add(other)
    db.flush()
    made.agent.user_id = other.id
    assert "Agent belongs to the buyer" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_cart_total_mismatch_fails(db, made):
    made.order.total = Decimal("9.99")
    assert "Line totals add up to the order total" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_malformed_cart_fails(db, made):
    made.order.cart_json = [{"product_id": "p", "qty": 50, "unit_price": "3.5", "category": "groceries"}]
    assert "Cart is well formed" in run_preflight(db, made.order, user_approved=False)["failed"]
    made.order.cart_json = []
    assert "Cart is well formed" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_order_over_the_hard_cap_fails(db, made):
    made.order.total = Decimal("2600.00")
    made.order.cart_json = [{**made.order.cart_json[0], "unit_price": "2600.00"}]
    r = run_preflight(db, made.order, user_approved=False)
    assert r["failed"] == ["Order total within the per-order limit"]


def test_cart_other_than_approved_fails_but_a_lower_price_is_fine(db, made):
    line = made.order.cart_json[0]
    made.intent.approved_cart = [{"product_id": line["product_id"], "qty": 1, "unit_price": "3.50",
                                  "merchant": "freshmart"}]
    db.flush()
    from app.intents import verify_intent_signature
    assert not verify_intent_signature(made.intent)
    r = run_preflight(db, made.order, user_approved=False)
    assert "Request is signed" in r["failed"]

    from app.intents import new_signed_intent
    signed = new_signed_intent(user_id=made.user.id, agent_id=made.agent.id, request_text="buy groceries",
                               approved_cart=[{"product_id": line["product_id"], "qty": 1, "unit_price": "4.00",
                                               "merchant": "freshmart"}])
    db.add(signed)
    db.flush()
    made.order.intent_id = signed.id
    assert run_preflight(db, made.order, user_approved=False)["passed"] is True
    made.order.cart_json = [{**line, "qty": 2}]
    made.order.total = Decimal("7.00")
    assert "Cart matches what you approved" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_a_second_open_order_for_the_same_request_fails(db, made):
    twin = Order(id=new_id("ord"), intent_id=made.order.intent_id, agent_id=made.agent.id, user_id=made.user.id,
                 merchant="freshmart", cart_json=made.order.cart_json, total=made.order.total, currency="USD",
                 status="pending_approval")
    db.add(twin)
    db.flush()
    assert "No other open order for this request" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_same_store_and_amount_paid_minutes_ago_fails(db, made):
    paid = Order(id=new_id("ord"), intent_id=made.order.intent_id, agent_id=made.agent.id, user_id=made.user.id,
                 merchant="freshmart", cart_json=[], total=made.order.total, currency="USD", status="captured")
    db.add(paid)
    db.flush()
    failed = run_preflight(db, made.order, user_approved=False)["failed"]
    assert "Not a duplicate of a recent payment" in failed


def test_user_daily_cap_fails(db, made):
    big = Order(id=new_id("ord"), intent_id=made.order.intent_id, agent_id=made.agent.id, user_id=made.user.id,
                merchant="other", cart_json=[], total=Decimal("4999.00"), currency="USD", status="captured")
    db.add(big)
    db.flush()
    assert "Within your daily spending limit" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_agent_daily_limit_fails(db, made, monkeypatch):
    monkeypatch.setenv("AGENT_ORDERS_PER_DAY", "0")
    assert "Agent under its daily order limit" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_missing_authorization_fails(db, made):
    made.order.authorization_id = None
    assert "Payment authorization exists" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_non_https_page_fails(db, made):
    made.order.page_urls = ["http://freshmart.example/p/milk"]
    assert "Store pages use HTTPS" in run_preflight(db, made.order, user_approved=False)["failed"]


def test_lab_fixture_pages_pass_only_when_fixtures_are_allowed(db, made):
    fixture = str((preflight.LAB_PAGES / "normal" / "normal_01_whole_milk.html").resolve())
    made.order.page_urls = [fixture]
    assert "Store pages use HTTPS" in run_preflight(db, made.order, user_approved=False)["failed"]
    assert run_preflight(db, made.order, user_approved=False, allow_fixtures=True)["passed"] is True
    for other in ("/etc/passwd", fixture + "/../../../../../etc/hosts.html", "http://freshmart.example/p"):
        made.order.page_urls = [other]
        assert "Store pages use HTTPS" in run_preflight(db, made.order, user_approved=False,
                                                        allow_fixtures=True)["failed"]


def test_a_failed_email_send_fails_the_last_check(db, made, monkeypatch):
    monkeypatch.setattr(preflight, "send_payment_notice", lambda u, o: False)
    r = run_preflight(db, made.order, user_approved=False)
    assert r["passed"] is False and r["failed"] == ["Payment notice emailed to you"]
    assert by_id(r, "P32")["status"] == "fail"
    assert made.order.shipping_address is None


@pytest.mark.parametrize("step,label", [("scan_injection", "No prompt injection found"),
                                        ("intent_diff", "Order matches your request"),
                                        ("graph_risk", "Store risk is low")])
def test_ai_warnings_fail_until_the_user_approves(db, made, step, label):
    set_row(db, made.order, step, "flag", score=80 if step == "graph_risk" else None)
    r = run_preflight(db, made.order, user_approved=False)
    assert r["passed"] is False and label in r["failed"]
    r = run_preflight(db, made.order, user_approved=True)
    assert r["passed"] is True
    assert by_id(r, {"scan_injection": "P26", "intent_diff": "P27", "graph_risk": "P28"}[step])["status"] == "accepted"


def test_price_anomaly_is_accepted_only_when_the_user_approves(db, made):
    set_row(db, made.order, "intent_diff", "flag", {"items": [{"explained": "yes"}], "price_anomaly": True})
    r = run_preflight(db, made.order, user_approved=False)
    assert "No price anomaly" in r["failed"]
    r = run_preflight(db, made.order, user_approved=True)
    assert r["passed"] is True and by_id(r, "P29")["status"] == "accepted"


def test_user_approval_does_not_excuse_other_failures(db, made):
    set_row(db, made.order, "scan_injection", "flag")
    made.user.shipping_address = None
    r = run_preflight(db, made.order, user_approved=True)
    assert r["passed"] is False and r["failed"] == ["Shipping address on file", "Shipping address is complete"]


def test_missing_ai_row_fails_even_when_the_user_approves(db, made):
    db.execute(Check.__table__.delete().where(Check.order_id == made.order.id, Check.step == "graph_risk"))
    assert "Store risk is low" in run_preflight(db, made.order, user_approved=True)["failed"]


def test_a_crashing_check_fails_instead_of_raising(db, made, monkeypatch):
    def boom(ctx):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(preflight, "_p02", boom)
    monkeypatch.setattr(preflight, "CHECKS", tuple((i, l, boom if i == "P02" else f) for i, l, f in preflight.CHECKS))
    r = run_preflight(db, made.order, user_approved=False)
    assert r["passed"] is False and by_id(r, "P02")["detail"] == "Could not be checked"


def sent_capture(monkeypatch, status=200, error=None):
    sent = []

    def post(url, json=None, headers=None, timeout=None):
        if error:
            raise error
        sent.append(json)
        return SimpleNamespace(status_code=status, text="")

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(notify.httpx, "post", post)
    return sent


def test_payment_notice_contains_amount_store_items_address_and_dispute_line(db, made, monkeypatch):
    sent = sent_capture(monkeypatch)
    assert notify.send_payment_notice(made.user, made.order) is True
    body = sent[0]
    assert body["to"] == [made.user.email]
    for part in ("3.50 USD", "freshmart", "1 x Item @ 3.50", "1 Main St", f"/orders/{made.order.id}",
                 "If you didn't ask for this, open the order and raise a dispute."):
        assert part in body["text"]
    assert "raise a dispute" in body["html"]


def test_payment_notice_failures_return_false_without_raising(db, made, monkeypatch):
    sent_capture(monkeypatch, status=500)
    assert notify.send_payment_notice(made.user, made.order) is False
    sent_capture(monkeypatch, error=httpx.ConnectError("down"))
    assert notify.send_payment_notice(made.user, made.order) is False


def test_payment_notice_without_a_key_succeeds_locally_and_fails_elsewhere(db, made, monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "WEB_ORIGIN", "http://localhost:3000")
    assert notify.send_payment_notice(made.user, made.order) is True
    monkeypatch.setattr(settings, "WEB_ORIGIN", "https://sepilo.space")
    assert notify.send_payment_notice(made.user, made.order) is False


def test_pipeline_gate_holds_when_a_check_fails(db, made):
    made.user.shipping_address = None
    decision, reasons = asyncio.run(core._preflight_gate(db, made.order, ["Within the rules"]))
    assert decision == "hold"
    assert reasons[0] == "Within the rules" and "Shipping address on file" in reasons
    row = db.execute(select(Check).where(Check.order_id == made.order.id, Check.step == "preflight")).scalar_one()
    assert row.result == "fail" and row.details_json["total"] == 32 and row.details_json["passed"] < 32


def test_pipeline_gate_lets_a_clean_order_through(db, made):
    decision, reasons = asyncio.run(core._preflight_gate(db, made.order, []))
    assert (decision, reasons) == ("capture", [])
    row = db.execute(select(Check).where(Check.order_id == made.order.id, Check.step == "preflight")).scalar_one()
    assert row.result == "pass" and row.details_json["passed"] == 32


def test_pipeline_gate_holds_when_preflight_crashes(db, made, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(core, "run_preflight", boom)
    decision, reasons = asyncio.run(core._preflight_gate(db, made.order, []))
    assert decision == "hold" and reasons == ["Security checks could not be completed"]


def test_approval_without_an_address_is_refused_and_nothing_is_captured(client, db):
    m = make_capturable_order(db)
    m.user.shipping_address = None
    db.flush()
    r = client.post(f"/orders/{m.order.id}/approval", json={"decision": "approve"})
    assert r.status_code == 409
    assert r.json()["error"] == "preflight_failed"
    assert "Shipping address on file" in r.json()["reason"]
    assert "capture" not in [c["op"] for c in paypal_service.mock_calls()]
    db.expire_all()
    assert db.get(Order, m.order.id).status == "pending_approval"
    row = db.execute(select(Check).where(Check.order_id == m.order.id, Check.step == "preflight")).scalar_one()
    assert row.result == "fail"


def test_approval_with_ai_warnings_captures_and_records_accepted(client, db):
    m = make_capturable_order(db)
    set_row(db, m.order, "scan_injection", "flag")
    set_row(db, m.order, "graph_risk", "flag", score=70)
    r = client.post(f"/orders/{m.order.id}/approval", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "captured"
    db.expire_all()
    done = db.get(Order, m.order.id)
    assert done.capture_id and done.shipping_address == m.user.shipping_address
    row = db.execute(select(Check).where(Check.order_id == m.order.id, Check.step == "preflight")).scalar_one()
    statuses = {c["id"]: c["status"] for c in row.details_json["checks"]}
    assert row.result == "pass" and statuses["P26"] == "accepted" and statuses["P28"] == "accepted"


def test_decline_does_not_run_the_checks(client, db):
    m = make_capturable_order(db)
    m.user.shipping_address = None
    db.flush()
    r = client.post(f"/orders/{m.order.id}/approval", json={"decision": "decline"})
    assert r.status_code == 200 and r.json()["status"] == "voided"
