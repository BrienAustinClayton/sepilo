"""Signed-in user's own data. Every route here requires a session and only touches rows the
user owns; the older open routes stay for the shopping agent, the attack lab and tests."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.agents import _agent_out
from app.api.approvals import ApprovalRequest, post_approval
from app.api.mandates import MandateCreate, MandatePatch, _http
from app.api.orders import _order_to_dict, user_order_dict
from app.api.vault import vault_setup
from app.auth import current_session, current_user, send_security_notice
from app.crypto.keys import load_public_key
from app.db import get_db
from app import hosted_agents, velocity
from app.ids import new_id
from app.intents import create_intent, intent_to_dict
from app.mandates import create_mandate, list_mandates_for_user, mandate_to_dict, revoke_mandate, update_mandate
from app.models import Agent, AgentRun, Intent, Mandate, Order, User, UserSession
from app.paypal import service as paypal
from app.service_errors import ServiceError

router = APIRouter(prefix="/me", tags=["me"])

BUCKETS: dict[str, tuple[str, ...]] = {
    "needs_approval": ("pending_approval",),
    "paid": ("captured",),
    "blocked": ("voided", "rejected", "failed"),
    "in_progress": ("received", "awaiting_payment", "authorized", "checking"),
}


def _agent_view(a: Agent) -> dict[str, Any]:
    return {**_agent_out(a), "managed": bool(a.managed), "kind": a.kind}


def _not_found(what: str) -> HTTPException:
    return HTTPException(404, detail={"error": "not_found", "reason": f"{what} not found"})


def _own_order(db: Session, user: User, order_id: str) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.user_id != user.id:
        raise _not_found("order")
    return order


def _own_agent(db: Session, user: User, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.user_id != user.id:
        raise _not_found("agent")
    return agent


def _own_mandate(db: Session, user: User, mandate_id: str) -> Mandate:
    m = db.get(Mandate, mandate_id)
    if m is None or db.get(Agent, m.agent_id).user_id != user.id:
        raise _not_found("spending rule")
    return m


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #

@router.get("/summary")
def summary(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0))
        .where(Order.user_id == user.id, Order.created_at >= month_start)
        .group_by(Order.status)
    ).all()
    by_status = {s: (n, Decimal(t)) for s, n, t in rows}
    count = lambda bucket: sum(by_status.get(s, (0, 0))[0] for s in BUCKETS[bucket])  # noqa: E731
    spent = sum((by_status.get(s, (0, Decimal(0)))[1] for s in BUCKETS["paid"]), Decimal(0))

    waiting_total = db.execute(
        select(func.count()).where(Order.user_id == user.id, Order.status == "pending_approval")
    ).scalar_one()
    agents = db.execute(select(Agent).where(Agent.user_id == user.id)).scalars().all()
    rules = list_mandates_for_user(db, user.id)
    recent = db.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(6)
    ).scalars().all()
    requests = db.execute(select(func.count()).where(Intent.user_id == user.id)).scalar_one()

    return {
        "currency": user.currency or "USD",
        "month": {
            "orders": sum(n for n, _ in by_status.values()),
            "paid": count("paid"),
            "blocked": count("blocked"),
            "spent": str(spent.quantize(Decimal("0.01"))),
        },
        "needs_approval": waiting_total,
        "agents_active": sum(1 for a in agents if a.revoked_at is None),
        "rules_active": sum(1 for m in rules if m.revoked_at is None),
        "requests": requests,
        "payment_connected": paypal.has_saved_payment(user.paypal_payment_token),
        "recent_orders": [_order_to_dict(o) for o in recent],
    }


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #

@router.get("/orders")
def orders(
    view: Literal["all", "needs_approval", "paid", "blocked", "in_progress"] = Query(default="all"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Order).where(Order.user_id == user.id)
    if view != "all":
        stmt = stmt.where(Order.status.in_(BUCKETS[view]))
    # Waiting approvals: biggest first, so the order that matters most isn't buried (approval fatigue)
    stmt = stmt.order_by(Order.total.desc() if view == "needs_approval" else Order.created_at.desc()).limit(500)
    return [_order_to_dict(o) for o in db.execute(stmt).scalars().all()]


@router.get("/orders/{order_id}")
def order(order_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_order_dict(_own_order(db, user, order_id))


@router.post("/orders/{order_id}/approval")
def approve(order_id: str, body: ApprovalRequest, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    _own_order(db, user, order_id)
    return post_approval(order_id, body, db)


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #

class AgentConnect(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    public_key: str = Field(min_length=1, max_length=64)
    device_id: str = Field(default="", max_length=128)


@router.get("/agents")
def agents(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    hosted_agents.ensure_default_agents(db, user.id)
    rows = db.execute(
        select(Agent).where(Agent.user_id == user.id).order_by(Agent.created_at.desc())
    ).scalars().all()
    return [_agent_view(a) for a in rows]


@router.post("/agents", status_code=201)
def connect_agent(body: AgentConnect, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        load_public_key(body.public_key)
    except ValueError:
        raise HTTPException(422, detail={"error": "invalid_public_key",
                                         "reason": "That isn't a valid Ed25519 public key (base64url, 32 bytes)."})
    agent = Agent(id=new_id("agt"), user_id=user.id, name=body.name, public_key=body.public_key,
                  device_id=body.device_id or "unspecified", verified=False)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    send_security_notice(user.email, "A new agent was connected to your Sepilo account",
                         f"The agent “{agent.name}” can now shop for you within your spending rules.")
    return _agent_view(agent)


@router.post("/agents/{agent_id}/revoke")
def revoke_agent(agent_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = _own_agent(db, user, agent_id)
    if agent.revoked_at is None:
        agent.revoked_at = datetime.now(timezone.utc)
        db.commit()
    db.refresh(agent)
    return _agent_view(agent)


# --------------------------------------------------------------------------- #
# Spending rules (mandates)
# --------------------------------------------------------------------------- #

@router.get("/mandates")
def mandates(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [mandate_to_dict(m) for m in list_mandates_for_user(db, user.id)]


@router.post("/mandates", status_code=201)
def add_mandate(body: MandateCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _own_agent(db, user, body.agent_id)
    try:
        return mandate_to_dict(create_mandate(db, body.model_dump()))
    except ServiceError as e:
        raise _http(e)


@router.patch("/mandates/{mandate_id}")
def edit_mandate(mandate_id: str, body: MandatePatch, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    _own_mandate(db, user, mandate_id)
    patch = body.model_dump(exclude_unset=True)
    if patch.get("agent_id"):
        _own_agent(db, user, patch["agent_id"])
    try:
        return mandate_to_dict(update_mandate(db, mandate_id, patch))
    except ServiceError as e:
        raise _http(e)


@router.post("/mandates/{mandate_id}/revoke")
def end_mandate(mandate_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _own_mandate(db, user, mandate_id)
    try:
        return mandate_to_dict(revoke_mandate(db, mandate_id))
    except ServiceError as e:
        raise _http(e)


# --------------------------------------------------------------------------- #
# Purchase requests (intents)
# --------------------------------------------------------------------------- #

class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agent_id: str = Field(min_length=1, max_length=64)
    request_text: str = Field(min_length=3, max_length=2000)


def _latest_runs(db: Session, user: User, intent_ids: list[str]) -> dict[str, dict]:
    if not intent_ids:
        return {}
    runs = db.execute(
        select(AgentRun).where(AgentRun.user_id == user.id, AgentRun.intent_id.in_(intent_ids))
        .order_by(AgentRun.started_at.asc())
    ).scalars().all()
    latest = {r.intent_id: r for r in runs}
    orders = {o.id: o for o in db.execute(
        select(Order).where(Order.id.in_([r.order_id for r in latest.values() if r.order_id]))
    ).scalars()} if any(r.order_id for r in latest.values()) else {}
    return {i: hosted_agents.run_to_dict(r, orders.get(r.order_id)) for i, r in latest.items()}


def _request_view(i: Intent, agent: Agent | None, orders: int, run: dict | None) -> dict[str, Any]:
    return {**intent_to_dict(i), "agent_name": agent.name if agent else None,
            "agent_managed": bool(agent and agent.managed), "orders": orders, "run": run}


@router.get("/requests")
def requests(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Intent).where(Intent.user_id == user.id).order_by(Intent.signed_at.desc()).limit(200)
    ).scalars().all()
    order_counts = dict(db.execute(
        select(Order.intent_id, func.count()).where(Order.user_id == user.id).group_by(Order.intent_id)
    ).all())
    agents = {a.id: a for a in db.execute(select(Agent).where(Agent.user_id == user.id)).scalars()}
    runs = _latest_runs(db, user, [i.id for i in rows])
    return [_request_view(i, agents.get(i.agent_id), order_counts.get(i.id, 0), runs.get(i.id)) for i in rows]


def _start(db: Session, background: BackgroundTasks, user: User, intent_id: str, agent: Agent) -> dict:
    run = hosted_agents.start_run(db, intent_id, user.id, agent.id)
    background.add_task(hosted_agents.execute_run, run.id)
    return hosted_agents.run_to_dict(run)


@router.post("/requests", status_code=201)
def add_request(body: RequestCreate, background: BackgroundTasks, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    agent = _own_agent(db, user, body.agent_id)
    if agent.revoked_at is not None:
        raise HTTPException(409, detail={"error": "agent_revoked", "reason": "This agent is disconnected."})
    try:
        i = create_intent(db, user_id=user.id, agent_id=agent.id, request_text=body.request_text)
    except ServiceError as e:
        raise HTTPException(e.status_code, detail={"error": e.error, "reason": e.reason})
    run = _start(db, background, user, i.id, agent) if agent.managed else None
    return _request_view(i, agent, 0, run)


@router.post("/requests/{request_id}/run", status_code=202)
def rerun_request(request_id: str, background: BackgroundTasks, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    i = db.get(Intent, request_id)
    if i is None or i.user_id != user.id:
        raise _not_found("purchase request")
    agent = _own_agent(db, user, i.agent_id)
    if not agent.managed:
        raise HTTPException(409, detail={"error": "not_hosted",
                                         "reason": "Only agents hosted by Sepilo can be run from here."})
    if agent.revoked_at is not None:
        raise HTTPException(409, detail={"error": "agent_revoked", "reason": "This agent is disconnected."})
    current = _latest_runs(db, user, [i.id]).get(i.id)
    if current and current["status"] == "running":
        raise HTTPException(409, detail={"error": "already_running", "reason": "The agent is already working on this."})
    if current and current["status"] == "ordered":
        raise HTTPException(409, detail={"error": "already_ordered", "reason": "This request already has an order."})
    return _start(db, background, user, i.id, agent)


# --------------------------------------------------------------------------- #
# Payment method
# --------------------------------------------------------------------------- #

@router.get("/payment")
def payment(user: User = Depends(current_user)) -> dict[str, Optional[bool]]:
    return {"connected": paypal.has_saved_payment(user.paypal_payment_token)}


@router.post("/payment/setup")
def payment_setup(user: User = Depends(current_user), sess: UserSession = Depends(current_session),
                  db: Session = Depends(get_db)):
    velocity.require_fresh_sign_in(sess)  # someone with a stolen session can't swap the payment method
    return vault_setup(user.id, db)
