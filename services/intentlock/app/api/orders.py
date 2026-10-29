"""Orders router — GET /orders, GET /orders/{id}.

POST /orders/{id}/approval is owned by P1-T10 (approvals.py).
GET  /orders/{id}/proof  is owned by P1-T11 (proofs.py).
The stubs below keep the routes importable while those tasks are built.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Approval, Check, Order
from app.signing import iso_z

router = APIRouter(tags=["orders"])


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------

def _check_to_dict(c: Check) -> dict[str, Any]:
    return {
        "id": c.id,
        "order_id": c.order_id,
        "step": c.step,
        "result": c.result,
        "score": float(c.score) if c.score is not None else None,
        "details": c.details_json,
        "duration_ms": c.duration_ms,
        "created_at": iso_z(c.created_at),
    }


def _approval_to_dict(a: Approval) -> dict[str, Any]:
    return {
        "id": a.id,
        "order_id": a.order_id,
        "requested_at": iso_z(a.requested_at),
        "decided_at": iso_z(a.decided_at) if a.decided_at is not None else None,
        "decision": a.decision,
        "expires_at": iso_z(a.expires_at) if a.expires_at is not None else None,
    }


def _user_safe_details(c: Check) -> Optional[dict[str, Any]]:
    """What a shopper may see about a check: plain reasons, never scores, probabilities or thresholds."""
    d = c.details_json if isinstance(c.details_json, dict) else {}
    if c.step == "intent_diff":
        items = [{k: i.get(k) for k in ("product_id", "title", "explained", "issue", "reason")}
                 for i in d.get("items") or [] if isinstance(i, dict)]
        return {"items": items, "price_anomaly": bool(d.get("price_anomaly"))}
    if c.step == "decide":
        return {"decision": d.get("decision"), "reasons": list(d.get("reasons") or [])}
    if c.step == "preflight":
        items = [{k: i.get(k) for k in ("id", "label", "status", "detail")}
                 for i in d.get("checks") or [] if isinstance(i, dict)]
        return {"checks": items, "passed": d.get("passed"), "total": d.get("total")} if items else None
    if c.step in ("capture_or_void", "authorize_payment"):
        return {"action": d.get("action")} if d.get("action") else None
    return None


def preflight_summary(check: Optional[Check]) -> Optional[dict[str, Any]]:
    """Headline of the 32 payment checks for list views: how many passed and the first failures."""
    if check is None or not isinstance(check.details_json, dict):
        return None
    d = check.details_json
    items = [c for c in d.get("checks") or [] if isinstance(c, dict)]
    ok = sum(1 for c in items if c.get("status") in ("pass", "accepted"))
    passed = d["passed"] if isinstance(d.get("passed"), int) else ok
    total = d["total"] if isinstance(d.get("total"), int) else 32
    failed = [str(c.get("label")) for c in items if c.get("status") == "fail" and c.get("detail") != "not_sent"]
    return {"passed": passed, "total": total, "failed": failed[:2]}


def user_order_dict(order: Order) -> dict[str, Any]:
    """Order as its owner sees it (the /me routes): checks without internals."""
    d = _order_to_dict(order, include_checks=True)
    by_id = {c.id: c for c in order.checks}
    d["checks"] = [{**c, "score": None, "details": _user_safe_details(by_id[c["id"]])} for c in d["checks"]]
    return d


def _order_to_dict(order: Order, *, include_checks: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": order.id,
        "intent_id": order.intent_id,
        "agent_id": order.agent_id,
        "user_id": order.user_id,
        "merchant": order.merchant,
        "cart": order.cart_json,
        "total": str(Decimal(str(order.total)).quantize(Decimal("0.01"))),
        "currency": order.currency,
        "paypal_order_id": order.paypal_order_id,
        "authorization_id": order.authorization_id,
        "capture_id": order.capture_id,
        "status": order.status,
        "pay_url": order.payer_action_url if order.status == "awaiting_payment" else None,
        "decision": order.decision,
        "reasons": order.reasons if order.reasons is not None else [],
        "page_urls": order.page_urls,
        "shipping_address": order.shipping_address,
        "trace_id": order.trace_id,
        "created_at": iso_z(order.created_at),
        "updated_at": iso_z(order.updated_at),
    }
    if include_checks:
        checks = sorted(order.checks, key=lambda c: c.created_at)
        d["checks"] = [_check_to_dict(c) for c in checks]
        d["approval"] = _approval_to_dict(order.approval) if order.approval else None
    return d


# ---------------------------------------------------------------------------
# GET /orders
# ---------------------------------------------------------------------------

@router.get("/orders")
def list_orders(
    user_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Order)
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.created_at.desc())
    orders = list(db.execute(stmt).scalars().all())
    return [_order_to_dict(o) for o in orders]


# ---------------------------------------------------------------------------
# GET /orders/{id}
# ---------------------------------------------------------------------------

@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "reason": "order not found"},
        )
    return _order_to_dict(order, include_checks=True)
