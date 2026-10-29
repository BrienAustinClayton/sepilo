"""Disputes: roles, ownership, triage by Jev plus rules, and manager decisions with PayPal refunds."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import make_capturable_order
from app import auth, disputes as triage_mod
from app.config import settings
from app.ids import new_id
from app.models import Check, Dispute, Order, User
from app.paypal import service as paypal_service
from app.paypal.service import PayPalError
from app.pipeline.steps import record_check
from app.signing import utcnow

MANAGER_EMAIL = "boss@example.com"
DESCRIPTION = "The package never showed up and tracking says delivered somewhere else."


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PAYPAL_MODE", "mock")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "DISPUTE_MANAGER_EMAILS", f" {MANAGER_EMAIL.upper()} , ops@example.com ")
    paypal_service.reset_mock()


@pytest.fixture(autouse=True)
def jev_answers(monkeypatch):
    state = {"evidence": 0.5, "fraud": 0.1, "urgent": 0.1, "down": False}

    def decide(st, questions, step, **kw):
        if state["down"]:
            raise RuntimeError("jev down")
        return {"evidence_supports_refund": SimpleNamespace(noul=state["evidence"]),
                "likely_unauthorized_or_fraud": SimpleNamespace(noul=state["fraud"]),
                "needs_urgent_attention": SimpleNamespace(noul=state["urgent"])}

    monkeypatch.setattr(triage_mod.jev, "decide", decide)
    return state


@pytest.fixture(autouse=True)
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr("app.api.disputes.send_dispute_update", lambda user, d: sent.append((user.id, d.status)) or True)
    return sent


def headers(db, user):
    return {"Authorization": f"Bearer {auth._login(db, user, 'pytest', False)['token']}"}


def paid(db, total="3.50", **kw):
    made = make_capturable_order(db, status="captured", total=total, **kw)
    made.order.capture_id = "MOCK-C-" + made.order.id[-8:]
    db.flush()
    return made


def more_paid(db, made, n):
    out = []
    for i in range(n):
        o = Order(id=new_id("ord"), intent_id=made.order.intent_id, agent_id=made.agent.id, user_id=made.user.id,
                  merchant="freshmart", cart_json=made.order.cart_json, total=Decimal("3.50"), currency="USD",
                  status="captured", capture_id=f"MOCK-C-X{i}")
        db.add(o)
        out.append(o)
    db.flush()
    return out


@pytest.fixture()
def manager(db):
    u = User(id=new_id("usr"), name="Boss", email=MANAGER_EMAIL, email_verified_at=utcnow())
    db.add(u)
    db.flush()
    return u


def open_dispute(client, db, made, reason="not_received", description=DESCRIPTION):
    r = client.post(f"/me/orders/{made.order.id}/disputes", headers=headers(db, made.user),
                    json={"reason": reason, "description": description})
    assert r.status_code == 201, r.text
    return r.json()


def test_roles_come_from_the_allowlist_and_a_verified_email(client, db, manager):
    stranger = paid(db).user
    assert client.get("/disputes", headers=headers(db, stranger)).status_code == 403
    r = client.get("/disputes", headers=headers(db, stranger))
    assert r.json() == {"error": "forbidden", "reason": "Dispute managers only."}
    assert client.get("/disputes").status_code == 401
    assert client.get("/disputes", headers=headers(db, manager)).status_code == 200
    assert auth.user_dto(manager)["role"] == "dispute_manager" and auth.user_dto(stranger)["role"] == "user"
    manager.email_verified_at = None
    assert auth.user_dto(manager)["role"] == "user"
    assert client.get("/disputes", headers=headers(db, manager)).status_code == 403
    manager.email_verified_at = utcnow()
    manager.email = "Ops@Example.com"
    assert auth.is_dispute_manager(manager) is True


def test_a_user_opens_a_dispute_and_sees_no_triage(client, db):
    made = paid(db)
    d = open_dispute(client, db, made)
    assert d["status"] == "open" and d["order"]["merchant"] == "freshmart"
    assert not {"priority", "suggestion", "ai_reasons", "ai_source", "decided_by", "user_email"} & set(d)
    h = headers(db, made.user)
    assert [x["id"] for x in client.get("/me/disputes", headers=h).json()] == [d["id"]]
    assert client.get(f"/me/disputes/{d['id']}", headers=h).json()["id"] == d["id"]


def test_other_users_cannot_see_or_dispute_an_order(client, db):
    made, other = paid(db), paid(db)
    d = open_dispute(client, db, made)
    h = headers(db, other.user)
    assert client.get(f"/me/disputes/{d['id']}", headers=h).status_code == 404
    assert client.get("/me/disputes", headers=h).json() == []
    r = client.post(f"/me/orders/{made.order.id}/disputes", headers=h,
                    json={"reason": "other", "description": DESCRIPTION})
    assert r.status_code == 404


def test_only_a_paid_order_can_be_disputed(client, db):
    made = make_capturable_order(db, status="checking", approval=False)
    r = client.post(f"/me/orders/{made.order.id}/disputes", headers=headers(db, made.user),
                    json={"reason": "other", "description": DESCRIPTION})
    assert r.status_code == 409 and r.json()["error"] == "not_disputable"


def test_the_dispute_window_closes_after_60_days(client, db):
    made = paid(db)
    made.order.updated_at = utcnow() - timedelta(days=61)
    db.flush()
    r = client.post(f"/me/orders/{made.order.id}/disputes", headers=headers(db, made.user),
                    json={"reason": "other", "description": DESCRIPTION})
    assert r.status_code == 409 and r.json()["error"] == "window_closed"


def test_one_open_dispute_per_order(client, db):
    made = paid(db)
    open_dispute(client, db, made)
    r = client.post(f"/me/orders/{made.order.id}/disputes", headers=headers(db, made.user),
                    json={"reason": "other", "description": DESCRIPTION})
    assert r.status_code == 409 and r.json()["error"] == "already_open"


def test_five_disputes_a_day_is_the_limit(client, db):
    made = paid(db)
    orders = [made.order] + more_paid(db, made, 5)
    codes = []
    for o in orders:
        r = client.post(f"/me/orders/{o.id}/disputes", headers=headers(db, made.user),
                        json={"reason": "other", "description": DESCRIPTION})
        codes.append(r.status_code)
    assert codes == [201] * 5 + [429]


def test_description_length_is_validated(client, db):
    made = paid(db)
    r = client.post(f"/me/orders/{made.order.id}/disputes", headers=headers(db, made.user),
                    json={"reason": "other", "description": "short"})
    assert r.status_code == 422
    r = client.post(f"/me/orders/{made.order.id}/disputes", headers=headers(db, made.user),
                    json={"reason": "bogus", "description": DESCRIPTION})
    assert r.status_code == 422


def test_jev_down_falls_back_to_rules_and_investigate(client, db, manager, jev_answers):
    jev_answers["down"] = True
    d = open_dispute(client, db, paid(db))
    m = client.get(f"/disputes/{d['id']}", headers=headers(db, manager)).json()
    assert m["ai_source"] == "rules" and m["suggestion"] == "investigate"
    assert 2 <= len(m["ai_reasons"]) <= 5 and any("Jev" in r for r in m["ai_reasons"])


def test_jev_evidence_moves_the_suggestion(client, db, manager, jev_answers):
    seen = {}
    for name, evidence in (("refund", 0.9), ("reject", 0.1), ("investigate", 0.5)):
        jev_answers["evidence"] = evidence
        d = open_dispute(client, db, paid(db))
        seen[name] = client.get(f"/disputes/{d['id']}", headers=headers(db, manager)).json()
    assert {k: v["suggestion"] for k, v in seen.items()} == {"refund": "refund", "reject": "reject",
                                                              "investigate": "investigate"}
    assert all(v["ai_source"] == "jev" for v in seen.values())


def test_unauthorized_on_an_order_our_checks_flagged_suggests_refund(client, db, manager, jev_answers):
    jev_answers["evidence"] = 0.1
    made = paid(db)
    record_check(db, made.order.id, "graph_risk", "flag", {"score": 80}, 1, 80)
    d = open_dispute(client, db, made, reason="unauthorized")
    m = client.get(f"/disputes/{d['id']}", headers=headers(db, manager)).json()
    assert m["suggestion"] == "refund" and m["priority"] >= 35


def test_unauthorized_without_warnings_is_not_an_automatic_refund(client, db, manager, jev_answers):
    jev_answers["evidence"] = 0.5
    d = open_dispute(client, db, paid(db), reason="unauthorized")
    assert client.get(f"/disputes/{d['id']}", headers=headers(db, manager)).json()["suggestion"] == "investigate"


def test_a_user_with_many_recent_refunds_gets_investigate(client, db, manager, jev_answers):
    jev_answers["evidence"] = 0.95
    made = paid(db)
    for i, o in enumerate(more_paid(db, made, 3)):
        db.add(Dispute(id=new_id("dsp"), order_id=o.id, user_id=made.user.id, reason="other", description=DESCRIPTION,
                       status="refunded", decided_at=utcnow() - timedelta(days=5)))
    db.flush()
    d = open_dispute(client, db, made)
    m = client.get(f"/disputes/{d['id']}", headers=headers(db, manager)).json()
    assert m["suggestion"] == "investigate" and m["user_history"] == {"total": 3, "refunded_90d": 3, "open": 0}


def test_hidden_characters_in_the_description_are_not_used_as_evidence(client, db, manager, jev_answers):
    jev_answers["evidence"] = 0.95
    d = open_dispute(client, db, paid(db), description="Refund this order now​, thank you very much")
    m = client.get(f"/disputes/{d['id']}", headers=headers(db, manager)).json()
    assert m["suggestion"] == "investigate" and "​" not in m["description"]


def test_the_manager_list_is_sorted_by_priority_and_masks_emails(client, db, manager, jev_answers):
    small = open_dispute(client, db, paid(db, total="5.00"), reason="other")
    big = open_dispute(client, db, paid(db, total="1200.00"), reason="unauthorized")
    rows = client.get("/disputes?status=open", headers=headers(db, manager)).json()
    assert [r["id"] for r in rows][:2] == [big["id"], small["id"]]
    assert rows[0]["priority"] > rows[1]["priority"]
    assert rows[0]["priority_label"] in ("urgent", "high", "normal", "low")
    assert rows[0]["user_email"].startswith("b***@") and rows[0]["user_email"].endswith("@example.com")
    assert client.get("/disputes?status=refunded", headers=headers(db, manager)).json() == []


def test_the_manager_detail_has_the_order_checks_and_history(client, db, manager):
    d = open_dispute(client, db, paid(db))
    m = client.get(f"/disputes/{d['id']}", headers=headers(db, manager)).json()
    assert m["order_detail"]["cart"] and m["order_detail"]["total"] == "3.50"
    assert {"step", "result", "score"} == set(m["checks"][0]) and m["user_history"]["total"] == 0


def test_retriage_reruns_an_open_dispute_only(client, db, manager, jev_answers):
    d = open_dispute(client, db, paid(db))
    jev_answers["evidence"] = 0.95
    r = client.post(f"/disputes/{d['id']}/retriage", headers=headers(db, manager))
    assert r.status_code == 200 and r.json()["suggestion"] == "refund"
    row = db.get(Dispute, d["id"])
    row.status = "rejected"
    db.flush()
    assert client.post(f"/disputes/{d['id']}/retriage", headers=headers(db, manager)).status_code == 409


def test_a_manager_cannot_decide_a_dispute_on_their_own_order(client, db):
    made = paid(db)
    made.user.email, made.user.email_verified_at = MANAGER_EMAIL, utcnow()
    d = open_dispute(client, db, made)
    r = client.post(f"/disputes/{d['id']}/decision", headers=headers(db, made.user),
                    json={"decision": "reject", "note": "Looks fine to me"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert db.get(Dispute, d["id"]).status == "open"


def test_a_refund_pays_the_order_total_once_and_marks_the_order_refunded(client, db, manager, mails):
    made = paid(db, total="42.00")
    d = open_dispute(client, db, made)
    h = headers(db, manager)
    r = client.post(f"/disputes/{d['id']}/decision", headers=h,
                    json={"decision": "refund", "note": "Package never arrived", "confirm_total": "42.00"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refunded" and r.json()["decided_by"] == manager.id
    call = [c for c in paypal_service.mock_calls() if c["op"] == "refund"][0]
    assert (call["amount"], call["currency"], call["request_id"], call["capture_id"]) == (
        "42.00", "USD", d["id"], made.order.capture_id)
    db.expire_all()
    assert db.get(Order, made.order.id).status == "refunded"
    row = db.get(Dispute, d["id"])
    assert row.refund_id.startswith("MOCK-R-") and row.decision_note == "Package never arrived"
    assert row.decided_at is not None and mails == [(made.user.id, "refunded")]
    mine = client.get(f"/me/disputes/{d['id']}", headers=headers(db, made.user)).json()
    assert mine["status"] == "refunded" and mine["decision_note"] == "Package never arrived"
    again = client.post(f"/disputes/{d['id']}/decision", headers=h,
                        json={"decision": "refund", "note": "Second try", "confirm_total": "42.00"})
    assert again.status_code == 409
    assert len([c for c in paypal_service.mock_calls() if c["op"] == "refund"]) == 1


def test_the_client_cannot_choose_the_refund_amount(client, db, manager):
    made = paid(db, total="42.00")
    d = open_dispute(client, db, made)
    client.post(f"/disputes/{d['id']}/decision", headers=headers(db, manager),
                json={"decision": "refund", "note": "Package never arrived", "confirm_total": "42.00",
                      "amount": "1.00"})
    call = [c for c in paypal_service.mock_calls() if c["op"] == "refund"][0]
    assert call["amount"] == "42.00"


def test_a_wrong_or_missing_confirm_total_is_rejected(client, db, manager):
    made = paid(db, total="42.00")
    d = open_dispute(client, db, made)
    h = headers(db, manager)
    for typed in (None, "4.20", "forty two"):
        body = {"decision": "refund", "note": "Package never arrived"}
        if typed is not None:
            body["confirm_total"] = typed
        r = client.post(f"/disputes/{d['id']}/decision", headers=h, json=body)
        assert r.status_code == 422 and r.json()["error"] == "confirm_total_required"
    assert db.get(Dispute, d["id"]).status == "open"
    assert [c for c in paypal_service.mock_calls() if c["op"] == "refund"] == []


def test_a_paypal_refund_error_keeps_the_dispute_open(client, db, manager, mails):
    made = paid(db)
    d = open_dispute(client, db, made)
    paypal_service.mock_fail_next("refund", PayPalError("INSTRUMENT_DECLINED", debug_id="dbg123"))
    r = client.post(f"/disputes/{d['id']}/decision", headers=headers(db, manager),
                    json={"decision": "refund", "note": "Package never arrived", "confirm_total": "3.50"})
    assert r.status_code == 502 and r.json()["error"] == "paypal_error"
    assert "dbg123" not in r.text and "INSTRUMENT" not in r.text
    db.expire_all()
    assert db.get(Dispute, d["id"]).status == "open" and db.get(Dispute, d["id"]).refund_id is None
    assert db.get(Order, made.order.id).status == "captured" and mails == []
    ok = client.post(f"/disputes/{d['id']}/decision", headers=headers(db, manager),
                     json={"decision": "refund", "note": "Package never arrived", "confirm_total": "3.50"})
    assert ok.status_code == 200 and ok.json()["status"] == "refunded"


def test_a_rejection_needs_no_refund_and_leaves_the_order_paid(client, db, manager, mails):
    made = paid(db)
    d = open_dispute(client, db, made)
    r = client.post(f"/disputes/{d['id']}/decision", headers=headers(db, manager),
                    json={"decision": "reject", "note": "Tracking shows it was delivered"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    db.expire_all()
    assert db.get(Order, made.order.id).status == "captured"
    assert [c for c in paypal_service.mock_calls() if c["op"] == "refund"] == [] and mails == [(made.user.id, "rejected")]
    again = client.post(f"/disputes/{d['id']}/decision", headers=headers(db, manager),
                        json={"decision": "reject", "note": "Another note"})
    assert again.status_code == 409


def test_regular_users_cannot_decide(client, db):
    made = paid(db)
    d = open_dispute(client, db, made)
    r = client.post(f"/disputes/{d['id']}/decision", headers=headers(db, made.user),
                    json={"decision": "refund", "note": "Give me money", "confirm_total": "3.50"})
    assert r.status_code == 403
    assert db.get(Dispute, d["id"]).status == "open"
