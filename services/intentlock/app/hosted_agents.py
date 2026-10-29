"""IntentLock-hosted shopping agents.

The API creates the agent's Ed25519 key pair and keeps the private key sealed (AES-256-GCM, key derived
from AUTH_SECRET with HKDF). A run hands the key to the hosted agent service (apps/agent) over an
authenticated call; the service signs as that agent and reports back what happened.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import func, select, update

from app import runlog
from app.config import settings
from app.crypto.keys import generate_keypair_b64
from app.db import new_session
from app.ids import new_id
from app.models import Agent, AgentRun, Order

log = logging.getLogger("intentlock.hosted_agents")

RUN_TIMEOUT_S = 300
DEFAULT_AGENTS = (("channel3", "Sepilo Shopper"),)
STALE_AFTER = timedelta(minutes=10)
UNSENT_GRACE = timedelta(seconds=15)


class HostedAgentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _cfg(name: str) -> str | None:
    v = getattr(settings, name, None)
    return None if v in (None, "", "__FILL_ME__") else v


def _aead() -> AESGCM:
    secret = _cfg("AUTH_SECRET")
    if not secret:
        raise HostedAgentError(503, "not_configured", "Hosted agents are not configured (AUTH_SECRET).")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"intentlock/hosted-agent-key/v1").derive(secret.encode())
    return AESGCM(key)


def seal(private_key_b64: str, agent_id: str) -> str:
    nonce = os.urandom(12)
    ct = _aead().encrypt(nonce, private_key_b64.encode(), agent_id.encode())
    return "v1." + base64.urlsafe_b64encode(nonce + ct).decode()


def unseal(sealed: str, agent_id: str) -> str:
    if not sealed.startswith("v1."):
        raise HostedAgentError(500, "bad_key", "Agent key is unreadable.")
    raw = base64.urlsafe_b64decode(sealed[3:])
    return _aead().decrypt(raw[:12], raw[12:], agent_id.encode()).decode()


def new_hosted_agent(user_id: str, name: str, kind: str = "channel3") -> Agent:
    agent_id = new_id("agt")
    private_b64, public_b64 = generate_keypair_b64()
    return Agent(id=agent_id, user_id=user_id, name=name, public_key=public_b64,
                 device_id="intentlock-hosted", verified=True, managed=True, kind=kind,
                 secret_enc=seal(private_b64, agent_id))


def ensure_default_agents(db, user_id: str) -> None:
    """Give every user the Sepilo Shopper agent. A kind the user already has (even a disconnected one) is left alone."""
    try:
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"default-agents:{user_id}"))))
        have = set(db.execute(select(Agent.kind).where(Agent.user_id == user_id, Agent.managed.is_(True))).scalars())
        for kind, name in DEFAULT_AGENTS:
            if kind not in have:
                db.add(new_hosted_agent(user_id, name, kind))
        db.commit()
    except HostedAgentError:
        db.rollback()
        log.warning("hosted_agents.defaults_skipped user=%s", user_id)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def run_to_dict(run: AgentRun | None, order: Order | None = None) -> dict[str, Any] | None:
    if run is None:
        return None
    status, summary = run.status, run.summary
    started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
    if status == "running" and datetime.now(timezone.utc) - started > STALE_AFTER:
        status, summary = "failed", "The shopping agent didn't finish in time. Try again."
    return {
        "id": run.id,
        "status": status,
        "summary": summary,
        "errors": list(run.errors or []),
        "order_id": run.order_id,
        "order_status": order.status if order is not None else None,
        "pay_url": order.payer_action_url if order is not None and order.status == "awaiting_payment" else None,
        "started_at": _iso(started),
        "finished_at": _iso(run.finished_at),
    }


def order_summary(order: Order) -> str:
    lines = [l for l in order.cart_json or [] if isinstance(l, dict)]
    count = sum(int(l.get("qty") or 0) for l in lines)
    what = (f"{lines[0].get('qty')} × {str(lines[0].get('title') or 'item')[:120]}" if len(lines) == 1
            else f"{count} items")
    return f"Bought {what} from {order.merchant} for ${Decimal(str(order.total)):.2f}."


def _finish(db, run: AgentRun, status: str, summary: str, errors: list[str] | None = None,
            order_id: str | None = None) -> None:
    run.status = status
    run.summary = summary[:4000]
    run.errors = [str(e)[:500] for e in (errors or [])][:10]
    run.order_id = order_id
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    runlog.emit("agent_run.finished", run_id=run.id, intent_id=run.intent_id, agent_id=run.agent_id,
                status=status, order_id=order_id, response_status=run.response_status,
                response_ms=run.response_ms, summary=summary[:200])


def _claim(db, run_id: str, endpoint: str) -> bool:
    """Mark the run as sent exactly once, so a retry or the watchdog never double-sends it."""
    now = datetime.now(timezone.utc)
    got = db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == "running", AgentRun.dispatched_at.is_(None))
        .values(dispatched_at=now, endpoint=endpoint, attempts=AgentRun.attempts + 1)
        .returning(AgentRun.id)
    ).first()
    db.commit()
    return got is not None


def execute_run(run_id: str, db=None) -> None:
    """Ask the hosted agent service to shop for one purchase request and record what came back."""
    own = db is None
    db = db or new_session()
    try:
        run = db.get(AgentRun, run_id)
        if run is None or run.status != "running" or run.dispatched_at is not None:
            return
        agent = db.get(Agent, run.agent_id)
        url, secret = _cfg("AGENT_SERVICE_URL"), _cfg("AGENT_RUN_SECRET")
        if not url or not secret:
            missing = " and ".join(n for n, v in (("AGENT_SERVICE_URL", url), ("AGENT_RUN_SECRET", secret)) if not v)
            return _finish(db, run, "failed", f"The hosted shopping agent isn't configured ({missing} not set on the API).")
        if agent is None or not agent.managed or not agent.secret_enc or agent.revoked_at is not None:
            return _finish(db, run, "failed", "This agent can't be run by Sepilo.")
        try:
            key = unseal(agent.secret_enc, agent.id)
        except Exception:
            log.exception("hosted_agents.unseal_failed agent=%s", agent.id)
            return _finish(db, run, "failed", "The agent's key couldn't be read. Try another agent.")
        endpoint = f"{url.rstrip('/')}/run"
        if not _claim(db, run.id, endpoint):
            return
        db.refresh(run)
        runlog.emit("agent_run.dispatch", run_id=run.id, intent_id=run.intent_id, agent_id=agent.id,
                    endpoint=endpoint, attempt=run.attempts)
        t0 = time.monotonic()
        try:
            r = httpx.post(endpoint, timeout=RUN_TIMEOUT_S,
                           headers={"Authorization": f"Bearer {secret}", "X-IntentLock-Run": run.id},
                           json={"intent_id": run.intent_id, "agent_id": agent.id, "agent_private_key": key,
                                 **({"items": run.items} if run.items else
                                    {"product_id": run.product_id, "qty": run.qty or 1} if run.product_id else {})})
        except httpx.HTTPError as e:
            run.response_ms = int((time.monotonic() - t0) * 1000)
            run.response_excerpt = f"{type(e).__name__}: {str(e)[:300]}"
            return _finish(db, run, "failed", f"Couldn't reach the shopping agent at {endpoint} ({type(e).__name__}). Try again in a minute.")
        run.response_ms = int((time.monotonic() - t0) * 1000)
        run.response_status = r.status_code
        run.response_excerpt = (r.text or "")[:2000]
        try:
            data = r.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if r.status_code != 200:
            reason = data.get("reason")
            return _finish(db, run, "failed", f"The shopping agent stopped: {reason or f'HTTP {r.status_code}'}.")
        summary = str(data.get("summary") or "").strip()
        errors = data.get("errors") if isinstance(data.get("errors"), list) else []
        order_id = data.get("order_id") if isinstance(data.get("order_id"), str) else None
        if order_id:
            placed = db.get(Order, order_id)
            if placed is None or placed.intent_id != run.intent_id or placed.user_id != run.user_id:
                # The agent's reply is untrusted: only an order made for this request counts.
                runlog.emit("agent_run.foreign_order", run_id=run.id, order_id=order_id[:64])
                return _finish(db, run, "failed", "The shopping agent reported an order that isn't this purchase.")
            # What the user reads comes from the order itself, not from the agent's account of it, so an agent
            # can't hide that it bought something else, from another store or for more.
            summary = order_summary(placed)
            if placed.status == "awaiting_payment":
                summary += " Approve the payment in PayPal to finish."
            return _finish(db, run, "ordered", summary, errors, order_id)
        return _finish(db, run, "failed", summary or "The agent finished without placing an order.", errors)
    except Exception:
        log.exception("hosted_agents.run_crashed run=%s", run_id)
        try:
            db.rollback()
            run = db.get(AgentRun, run_id)
            if run is not None and run.status == "running":
                _finish(db, run, "failed", "Something went wrong while running the agent. Try again.")
        except Exception:
            log.exception("hosted_agents.run_crash_record_failed run=%s", run_id)
    finally:
        if own:
            db.close()


def start_run(db, intent_id: str, user_id: str, agent_id: str,
              product_id: str | None = None, qty: int | None = None, items: list | None = None) -> AgentRun:
    run = AgentRun(id=new_id("run"), intent_id=intent_id, user_id=user_id, agent_id=agent_id,
                   status="running", started_at=datetime.now(timezone.utc), attempts=0,
                   product_id=product_id, qty=qty, items=items)
    db.add(run)
    db.commit()
    runlog.emit("agent_run.queued", run_id=run.id, intent_id=intent_id, agent_id=agent_id, user_id=user_id)
    return run


def dispatch_async(run_id: str) -> None:
    threading.Thread(target=execute_run, args=(run_id,), name=f"agent-run-{run_id}", daemon=True).start()


def recover_runs(db, now: datetime | None = None) -> tuple[list[str], int]:
    """Watchdog: resend runs that were saved but never sent (e.g. the API restarted), and fail runs
    that were sent but never answered."""
    now = now or datetime.now(timezone.utc)
    unsent = db.execute(
        select(AgentRun.id).where(AgentRun.status == "running", AgentRun.dispatched_at.is_(None),
                                  AgentRun.started_at < now - UNSENT_GRACE)
    ).scalars().all()
    lost = db.execute(
        select(AgentRun).where(AgentRun.status == "running", AgentRun.dispatched_at.is_not(None),
                               AgentRun.dispatched_at < now - timedelta(seconds=RUN_TIMEOUT_S + 60))
    ).scalars().all()
    for run in lost:
        _finish(db, run, "failed", "The shopping agent never answered (the API may have restarted). Try again.")
    for rid in unsent:
        runlog.emit("agent_run.recovered", run_id=rid)
    return list(unsent), len(lost)


async def run_loop(interval_s: int = 20) -> None:
    import asyncio

    while True:
        try:
            db = new_session()
            try:
                unsent, failed = recover_runs(db)
            finally:
                db.close()
            for rid in unsent:
                dispatch_async(rid)
        except Exception:
            log.exception("hosted_agents.watchdog_error")
        await asyncio.sleep(interval_s)


SUGGEST_TIMEOUT_S = 90


def suggest(agent_id: str, message: str, history: list[dict], rules: list[dict]) -> dict[str, Any]:
    """Ask the hosted agent for products that answer a chat message within the agent's rules."""
    url, secret = _cfg("AGENT_SERVICE_URL"), _cfg("AGENT_RUN_SECRET")
    if not url or not secret:
        raise HostedAgentError(503, "not_configured", "The shopping assistant isn't configured yet.")
    endpoint = f"{url.rstrip('/')}/suggest"
    t0 = time.monotonic()
    try:
        r = httpx.post(endpoint, timeout=SUGGEST_TIMEOUT_S, headers={"Authorization": f"Bearer {secret}"},
                       json={"agent_id": agent_id, "message": message, "history": history, "rules": rules})
    except httpx.HTTPError as e:
        runlog.emit("chat.suggest_failed", agent_id=agent_id, endpoint=endpoint, error=type(e).__name__)
        raise HostedAgentError(502, "agent_unreachable", "The shopping assistant is waking up. Try again in a moment.")
    ms = int((time.monotonic() - t0) * 1000)
    try:
        data = r.json()
    except ValueError:
        data = {}
    runlog.emit("chat.suggest", agent_id=agent_id, endpoint=endpoint, response_status=r.status_code, response_ms=ms,
                products=len(data.get("products") or []) if isinstance(data, dict) else None)
    if r.status_code != 200 or not isinstance(data, dict):
        reason = data.get("reason") if isinstance(data, dict) else None
        raise HostedAgentError(502, "agent_error", f"The shopping assistant couldn't answer: {reason or f'HTTP {r.status_code}'}.")
    return data
