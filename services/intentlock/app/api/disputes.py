"""Disputes. Users raise one on a paid order (/me/...); dispute managers triage and decide (/disputes/...)."""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import disputes
from app.auth import current_user, require_dispute_manager
from app.db import get_db
from app.ids import new_id
from app.models import Check, Dispute, Order, User
from app.notify import send_dispute_update
from app.paypal import service as paypal
from app.signing import iso_z, utcnow
from app.untrusted import clean
from app.velocity import require_typed_total

log = logging.getLogger("intentlock.disputes")

me_router = APIRouter(prefix="/me", tags=["disputes"])
router = APIRouter(prefix="/disputes", tags=["disputes"])

REASONS = ("not_received", "not_as_described", "unauthorized", "duplicate", "other")
DESCRIPTION_MIN = 10
DESCRIPTION_MAX = 2000
NOTE_MAX = 1000
LIST_LIMIT = 200


class DisputeCreate(BaseModel):
    reason: Literal["not_received", "not_as_described", "unauthorized", "duplicate", "other"]
    description: str = Field(min_length=DESCRIPTION_MIN, max_length=DESCRIPTION_MAX)


class DisputeDecision(BaseModel):
    decision: Literal["refund", "reject"]
    note: str = Field(min_length=3, max_length=NOTE_MAX)
    confirm_total: Optional[str] = Field(default=None, max_length=20)


def _err(status: int, error: str, reason: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": error, "reason": reason})


def _money(v) -> str:
    return str(Decimal(str(v)).quantize(Decimal("0.01")))


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _user_view(d: Dispute, order: Order | None) -> dict[str, Any]:
    decided = d.status != "open"
    return {
        "id": d.id,
        "order_id": d.order_id,
        "reason": d.reason,
        "description": d.description,
        "status": d.status,
        "decision_note": d.decision_note if decided else None,
        "refund_id": d.refund_id if d.status == "refunded" else None,
        "created_at": iso_z(d.created_at),
        "decided_at": iso_z(d.decided_at) if d.decided_at else None,
        "order": None if order is None else {"merchant": order.merchant, "total": _money(order.total),
                                             "currency": order.currency},
    }


def _manager_view(d: Dispute, order: Order | None, user: User | None) -> dict[str, Any]:
    return {
        **_user_view(d, order),
        "user_email": mask_email(user.email if user else None),
        "priority": d.priority,
        "priority_label": d.priority_label,
        "suggestion": d.suggestion,
        "ai_reasons": list(d.ai_reasons or []),
        "ai_source": d.ai_source,
        "decided_by": d.decided_by,
    }


def _raise_rate_limited(db: Session, user: User) -> None:
    n = db.execute(
        select(func.count()).select_from(Dispute)
        .where(Dispute.user_id == user.id, Dispute.created_at >= utcnow() - timedelta(days=1))
    ).scalar_one()
    if n >= disputes.MAX_PER_DAY:
        raise _err(429, "rate_limited", "You've opened several disputes today. Try again tomorrow.")


@me_router.post("/orders/{order_id}/disputes", status_code=201)
def create_dispute(order_id: str, body: DisputeCreate, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    order = db.execute(select(Order).where(Order.id == order_id).with_for_update()).scalar_one_or_none()
    if order is None or order.user_id != user.id:
        raise _err(404, "not_found", "order not found")
    if order.status != "captured":
        raise _err(409, "not_disputable", "Only a paid order can be disputed.")
    if utcnow() - disputes.captured_at(db, order) > timedelta(days=disputes.WINDOW_DAYS):
        raise _err(409, "window_closed", f"Orders can be disputed for {disputes.WINDOW_DAYS} days after payment.")
    if db.execute(select(Dispute.id).where(Dispute.order_id == order.id, Dispute.status == "open")).first():
        raise _err(409, "already_open", "This order already has an open dispute.")
    _raise_rate_limited(db, user)
    description = clean(body.description, DESCRIPTION_MAX)
    if len(description) < DESCRIPTION_MIN:
        raise _err(422, "invalid_description", f"Describe the problem in at least {DESCRIPTION_MIN} characters.")
    d = Dispute(id=new_id("dsp"), order_id=order.id, user_id=user.id, reason=body.reason, description=description,
                status="open")
    disputes.triage(db, d, order, raw_description=body.description)
    db.add(d)
    db.commit()
    return _user_view(d, order)


@me_router.get("/disputes")
def my_disputes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Dispute, Order).join(Order, Order.id == Dispute.order_id)
        .where(Dispute.user_id == user.id).order_by(Dispute.created_at.desc()).limit(LIST_LIMIT)
    ).all()
    return [_user_view(d, o) for d, o in rows]


@me_router.get("/disputes/{dispute_id}")
def my_dispute(dispute_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Dispute, dispute_id)
    if d is None or d.user_id != user.id:
        raise _err(404, "not_found", "dispute not found")
    return _user_view(d, db.get(Order, d.order_id))


@router.get("")
def list_disputes(status: Literal["open", "refunded", "rejected", "failed"] = Query(default="open"),
                  _: User = Depends(require_dispute_manager), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Dispute, Order, User).join(Order, Order.id == Dispute.order_id).join(User, User.id == Dispute.user_id)
        .where(Dispute.status == status)
        .order_by(Dispute.priority.desc(), Dispute.created_at.asc()).limit(LIST_LIMIT)
    ).all()
    return [_manager_view(d, o, u) for d, o, u in rows]


def _get(db: Session, dispute_id: str) -> Dispute:
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise _err(404, "not_found", "dispute not found")
    return d


@router.get("/{dispute_id}")
def get_dispute(dispute_id: str, _: User = Depends(require_dispute_manager), db: Session = Depends(get_db)):
    d = _get(db, dispute_id)
    order = db.get(Order, d.order_id)
    user = db.get(User, d.user_id)
    checks = db.execute(select(Check).where(Check.order_id == d.order_id).order_by(Check.created_at, Check.id)).scalars()
    return {
        **_manager_view(d, order, user),
        "order_detail": {"id": order.id, "merchant": order.merchant, "cart": order.cart_json,
                         "total": _money(order.total), "currency": order.currency, "status": order.status,
                         "created_at": iso_z(order.created_at)},
        "checks": [{"step": c.step, "result": c.result, "score": None if c.score is None else float(c.score)}
                   for c in checks],
        "user_history": disputes.history(db, d.user_id, exclude_id=d.id),
    }


@router.post("/{dispute_id}/retriage")
def retriage(dispute_id: str, _: User = Depends(require_dispute_manager), db: Session = Depends(get_db)):
    d = db.execute(select(Dispute).where(Dispute.id == dispute_id).with_for_update()).scalar_one_or_none()
    if d is None:
        raise _err(404, "not_found", "dispute not found")
    if d.status != "open":
        raise _err(409, "conflict", "This dispute has already been decided.")
    order = db.get(Order, d.order_id)
    disputes.triage(db, d, order)
    db.commit()
    return _manager_view(d, order, db.get(User, d.user_id))


def _typed_total_or_422(total, typed: str | None) -> None:
    require_typed_total(total, typed)
    expected = Decimal(str(total)).quantize(Decimal("0.01"))
    try:
        ok = typed is not None and Decimal(str(typed).replace("$", "").replace(",", "").strip()) == expected
    except InvalidOperation:
        ok = False
    if not ok:
        raise _err(422, "confirm_total_required", f"Type the refund amount (${expected}) to refund this order.")


@router.post("/{dispute_id}/decision")
def decide(dispute_id: str, body: DisputeDecision, manager: User = Depends(require_dispute_manager),
           db: Session = Depends(get_db)):
    d = db.execute(select(Dispute).where(Dispute.id == dispute_id).with_for_update()).scalar_one_or_none()
    if d is None:
        raise _err(404, "not_found", "dispute not found")
    order = db.execute(select(Order).where(Order.id == d.order_id).with_for_update()).scalar_one()
    if order.user_id == manager.id or d.user_id == manager.id:
        raise _err(403, "forbidden", "You can't decide a dispute on your own order.")
    if d.status != "open":
        raise _err(409, "conflict", "This dispute has already been decided.")
    note = clean(body.note, NOTE_MAX)
    if len(note) < 3:
        raise _err(422, "invalid_note", "Add a short note for the customer.")
    if body.decision == "refund":
        _typed_total_or_422(order.total, body.confirm_total)
        if not order.capture_id:
            raise _err(409, "not_refundable", "This order has no captured payment to refund.")
        try:
            refund_id = paypal.refund(order.capture_id, Decimal(str(order.total)).quantize(Decimal("0.01")),
                                      order.currency, d.id)
        except paypal.PayPalError as e:
            log.warning("disputes.refund_failed dispute_id=%s code=%s debug_id=%s", d.id, e.code, e.debug_id)
            db.rollback()
            raise _err(502, "paypal_error", "PayPal could not complete the refund. The dispute is still open; "
                                            "try again in a moment.") from e
        d.status, d.refund_id = "refunded", refund_id
        order.status = "refunded"
    else:
        d.status = "rejected"
    d.decided_by, d.decided_at, d.decision_note = manager.id, utcnow(), note
    db.commit()
    send_dispute_update(db.get(User, d.user_id), d)
    return _manager_view(d, order, db.get(User, d.user_id))
