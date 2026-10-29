"""Approvals router — POST /orders/{order_id}/approval."""
from __future__ import annotations

import logging
import time
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Approval, Order
from app.paypal import service as paypal
from app.pipeline.steps import build_proof_step, ms_since, record_check, set_status
from app.preflight import TOTAL_CHECKS, preflight_details, run_preflight
from app.signing import utcnow
from app.velocity import require_typed_total

router = APIRouter(tags=["approvals"])
log = logging.getLogger("intentlock.approvals")

PREFLIGHT_ERROR_REASON = "Security checks could not be completed"


class ApprovalRequest(BaseModel):
    decision: str
    # Approving an order of HIGH_VALUE or more needs its total typed back (approval fatigue)
    confirm_total: Optional[str] = Field(default=None, max_length=20)

    @field_validator("decision")
    @classmethod
    def _valid(cls, v: str) -> str:
        if v not in ("approve", "decline"):
            raise ValueError("decision must be 'approve' or 'decline'")
        return v


def _preflight_or_409(db: Session, order: Order) -> None:
    t0 = time.perf_counter()
    try:
        result = run_preflight(db, order, user_approved=True)
    except Exception:
        log.exception("approvals.preflight_error order_id=%s", order.id)
        db.rollback()
        record_check(db, order.id, "preflight", "fail",
                     {"error": "preflight_error", "passed": 0, "total": TOTAL_CHECKS}, ms_since(t0))
        db.commit()
        raise HTTPException(status_code=409, detail={"error": "preflight_failed", "reason": PREFLIGHT_ERROR_REASON})
    record_check(db, order.id, "preflight", "pass" if result["passed"] else "fail",
                 preflight_details(result), ms_since(t0))
    if not result["passed"]:
        db.commit()
        raise HTTPException(status_code=409, detail={"error": "preflight_failed", "reason": "; ".join(result["failed"])})


def _order_response(order: Order, appr: Approval) -> dict:
    return {
        "order_id": order.id,
        "status": order.status,
        "decision": order.decision,
        "reasons": list(order.reasons or []),
        "approval": {
            "id": appr.id,
            "requested_at": appr.requested_at.isoformat() if appr.requested_at else None,
            "expires_at": appr.expires_at.isoformat() if appr.expires_at else None,
            "decided_at": appr.decided_at.isoformat() if appr.decided_at else None,
            "decision": appr.decision,
        },
    }


@router.post("/orders/{order_id}/approval")
def post_approval(
    order_id: str,
    body: ApprovalRequest,
    db: Session = Depends(get_db),
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "reason": "order not found"})

    appr = db.execute(select(Approval).where(Approval.order_id == order_id)).scalar_one_or_none()

    if order.status != "pending_approval" or appr is None:
        raise HTTPException(status_code=409, detail={"error": "conflict", "reason": "order is not awaiting approval"})

    now = utcnow()
    if appr.expires_at is not None:
        exp = appr.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now >= exp:
            raise HTTPException(status_code=409, detail={"error": "conflict", "reason": "approval window has expired"})

    if body.decision == "approve":
        require_typed_total(order.total, body.confirm_total)
        _preflight_or_409(db, order)
        try:
            capture_id = paypal.capture(order.authorization_id, request_id=order.id + "-approval")
        except paypal.PayPalError as e:
            raise HTTPException(status_code=502, detail={"error": "paypal_error", "reason": e.code}) from e
        order.capture_id = capture_id
        order.decision = "capture"
        set_status(order, "captured", [])
    else:
        try:
            paypal.void(order.authorization_id, request_id=order.id + "-decline")
        except paypal.PayPalError as e:
            raise HTTPException(status_code=502, detail={"error": "paypal_error", "reason": e.code}) from e
        order.decision = "void"
        set_status(order, "voided", [])

    appr.decision = body.decision
    appr.decided_at = now
    db.commit()

    build_proof_step(db, order_id)

    db.refresh(order)
    db.refresh(appr)
    return _order_response(order, appr)
