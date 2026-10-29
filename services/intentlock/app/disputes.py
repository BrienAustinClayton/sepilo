"""Dispute triage: code decides, Jev advises.

Code turns signals about the order, the reason and the user's history into a priority (0-100) and a
suggestion. Jev answers three probability questions about the user's words; its answers add to the priority
and can move the suggestion between refund, reject and investigate, but the rules below always apply.
The user's description is data: it is cleaned, never obeyed. If Jev fails, the suggestion is "investigate".
A dispute manager makes every final decision.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app import jev
from app.models import Check, Dispute, Order
from app.signing import to_utc, utcnow
from app.untrusted import clean, had_hidden_chars, talks_to_agent

log = logging.getLogger("intentlock.disputes")

STEP = "dispute_triage"
JEV_TIMEOUT_S = 4.0
WINDOW_DAYS = 60
MAX_PER_DAY = 5
HISTORY_DAYS = 90
ABUSE_REFUNDS = 3
EVIDENCE_REFUND = 0.7
EVIDENCE_REJECT = 0.3
BASE_PRIORITY = 10
REASON_POINTS = {"unauthorized": 30, "not_received": 15, "not_as_described": 12, "duplicate": 12, "other": 5}
AMOUNT_TIERS = ((Decimal("1000"), 25), (Decimal("500"), 20), (Decimal("100"), 12), (Decimal("25"), 5))
FLAG_POINTS = 8
FLAG_POINTS_MAX = 20
FRESH_POINTS = ((24, 10), (72, 5))
ABUSE_PENALTY = 10
JEV_FRAUD_POINTS = 15
JEV_URGENT_POINTS = 15
LABELS = ((80, "urgent"), (60, "high"), (35, "normal"), (0, "low"))
AI_STEPS = ("scan_injection", "intent_diff", "graph_risk")
REASON_TEXT = {
    "unauthorized": "says they did not authorize this payment",
    "not_received": "says the order never arrived",
    "not_as_described": "says the item is not as described",
    "duplicate": "says they were charged twice",
    "other": "gave another reason",
}


def label_for(priority: int) -> str:
    return next(name for floor, name in LABELS if priority >= floor)


def captured_at(db, order: Order):
    row = db.execute(
        select(Check.created_at).where(Check.order_id == order.id, Check.step == "capture_or_void",
                                       Check.result == "pass").order_by(Check.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    return to_utc(row or order.updated_at or order.created_at)


def flagged_steps(db, order: Order) -> list[str]:
    rows = db.execute(select(Check).where(Check.order_id == order.id).order_by(Check.created_at, Check.id)).scalars()
    latest = {c.step: c for c in rows}
    out = [s for s in AI_STEPS if s in latest and latest[s].result == "flag"]
    pre = latest.get("preflight")
    accepted = [c for c in ((pre.details_json or {}).get("checks") or []) if isinstance(c, dict)
                and c.get("status") == "accepted"] if pre is not None else []
    if accepted:
        out.append("preflight_accepted")
    return out


def history(db, user_id: str, exclude_id: str | None = None) -> dict[str, int]:
    since = utcnow() - timedelta(days=HISTORY_DAYS)
    base = select(func.count()).select_from(Dispute).where(Dispute.user_id == user_id)
    if exclude_id:
        base = base.where(Dispute.id != exclude_id)
    total = db.execute(base).scalar_one()
    refunded = db.execute(base.where(Dispute.status == "refunded", Dispute.decided_at >= since)).scalar_one()
    opened = db.execute(base.where(Dispute.status == "open")).scalar_one()
    return {"total": total, "refunded_90d": refunded, "open": opened}


def _amount_points(total: Decimal) -> int:
    return next((pts for floor, pts in AMOUNT_TIERS if total >= floor), 0)


def _questions() -> dict[str, dict]:
    return {
        "evidence_supports_refund": {"type": "noul", "instructions": (
            "The shopper's description gives specific, believable evidence that supports a refund for the "
            "stated reason (it is not vague, contradictory or generic)")},
        "likely_unauthorized_or_fraud": {"type": "noul", "instructions": (
            "The payment was probably not authorized by the shopper, or looks like fraud or an account takeover")},
        "needs_urgent_attention": {"type": "noul", "instructions": (
            "A human should look at this dispute urgently (large loss, fraud in progress, or a vulnerable shopper)")},
    }


def _p(ans: Any) -> float | None:
    v = getattr(ans, "noul", None)
    return float(v) if isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0 else None


def _jev(state: dict) -> dict[str, float | None] | None:
    try:
        answers = jev.decide(state, _questions(), STEP, timeout_s=JEV_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001  (Jev and its fallback both down)
        log.warning("disputes.jev_unavailable %s", type(e).__name__)
        return None
    return {k: _p(answers.get(k)) for k in _questions()}


def triage(db, dispute: Dispute, order: Order, raw_description: str | None = None) -> None:
    """Fill priority, label, suggestion, reasons and source on the dispute. Never raises."""
    try:
        _triage(db, dispute, order, raw_description)
    except Exception:  # noqa: BLE001
        log.exception("disputes.triage_error dispute_id=%s", dispute.id)
        dispute.priority, dispute.priority_label = 50, label_for(50)
        dispute.suggestion, dispute.ai_source = "investigate", "rules"
        dispute.ai_reasons = ["Automatic review could not be completed; a person needs to look at this."]


def _triage(db, dispute: Dispute, order: Order, raw_description: str | None) -> None:
    total = Decimal(str(order.total))
    hours = max((utcnow() - captured_at(db, order)).total_seconds() / 3600, 0)
    flags = flagged_steps(db, order)
    past = history(db, dispute.user_id, exclude_id=dispute.id)
    description = clean(dispute.description, 2000)
    submitted = raw_description if raw_description is not None else dispute.description
    steered = talks_to_agent(submitted) or had_hidden_chars(submitted)

    state = {
        "reason": dispute.reason,
        "description": description,
        "order": {"store": clean(order.merchant, 64), "total": str(total), "currency": order.currency,
                  "items": len(order.cart_json or []), "hours_since_payment": round(hours, 1)},
        "signals": {"flagged_checks": flags, "disputes_before": past["total"],
                    "refunded_last_90_days": past["refunded_90d"]},
    }
    jev_out = _jev(state)
    evidence = fraud = urgent = None
    if jev_out is not None:
        evidence, fraud, urgent = (jev_out[k] for k in ("evidence_supports_refund",
                                                       "likely_unauthorized_or_fraud", "needs_urgent_attention"))
        if steered:
            evidence = None

    points = BASE_PRIORITY + REASON_POINTS.get(dispute.reason, 5) + _amount_points(total)
    points += min(len(flags) * FLAG_POINTS, FLAG_POINTS_MAX)
    points += next((pts for limit, pts in FRESH_POINTS if hours < limit), 0)
    if past["refunded_90d"] >= ABUSE_REFUNDS:
        points -= ABUSE_PENALTY
    points += round((fraud or 0) * JEV_FRAUD_POINTS + (urgent or 0) * JEV_URGENT_POINTS)
    priority = max(0, min(100, points))

    if dispute.reason == "unauthorized" and flags:
        suggestion, basis = "refund", "The user says it was unauthorized and this order had warnings from our own checks."
    elif past["refunded_90d"] >= ABUSE_REFUNDS:
        suggestion, basis = "investigate", (
            f"This user has had {past['refunded_90d']} refunds in the last {HISTORY_DAYS} days, so check carefully.")
    elif evidence is not None and evidence >= EVIDENCE_REFUND:
        suggestion, basis = "refund", "The description gives believable evidence for a refund."
    elif evidence is not None and evidence <= EVIDENCE_REJECT:
        suggestion, basis = "reject", "The description gives little evidence for a refund."
    else:
        suggestion, basis = "investigate", "There is not enough evidence either way."

    reasons = [f"The user {REASON_TEXT.get(dispute.reason, REASON_TEXT['other'])}; ${total:.2f} was paid "
               f"{hours:.0f} hours ago."]
    if flags:
        reasons.append(f"{len(flags)} of our own checks on this order raised a warning.")
    if past["total"]:
        reasons.append(f"This user has opened {past['total']} other dispute(s), {past['refunded_90d']} refunded in "
                       f"the last {HISTORY_DAYS} days.")
    if steered:
        reasons.append("The description contains text aimed at an AI, so it was not used for the suggestion.")
    if jev_out is None:
        reasons.append("Jev could not review this dispute, so it was triaged by rules only.")
        suggestion, basis = "investigate", "Jev was unavailable, so a person should look at it."
    reasons.append(basis)

    dispute.priority = priority
    dispute.priority_label = label_for(priority)
    dispute.suggestion = suggestion
    dispute.ai_reasons = [r[:300] for r in (reasons if len(reasons) <= 5 else reasons[:1] + reasons[-4:])]
    dispute.ai_source = "jev" if jev_out is not None else "rules"
