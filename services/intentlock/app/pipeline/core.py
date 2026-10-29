"""Pipeline orchestration core: one code path for local and Render executors."""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Awaitable, Callable, Protocol

from sqlalchemy import select

from app.config import settings
from app.mandates import OrderDraft, check_mandate, select_mandate_for_agent, spent_in_period
from app.models import Agent, Check, Intent, Order
from app.paypal import service as paypal_service
from app.paypal.service import PayPalError
from app.pipeline import limits
from app.pipeline.context import (
    CheckoutOutcome, PipelineContext, StepRun, build_context, outcome_from_order,
)
from app.pipeline.steps import (
    build_proof_step, decision_result, ensure_approval, graph_result, injection_result,
    intent_diff_result, ms_since, record_check, record_skipped, set_status,
)
from app.policy import decide
from app.preflight import TOTAL_CHECKS, preflight_details, run_preflight
from app.signing import iso_z, utcnow
from app.velocity import PENDING_APPROVALS_PER_AGENT, pending_approvals

log = logging.getLogger("intentlock.pipeline")

PAYMENT_FAILED_REASON = "Payment could not be authorized"
CHECKOUT_FAILED_REASON = "Checkout could not be completed"
PIPELINE_HOLD_REASON = "Policy check could not be completed; needs your review"
NO_SAVED_PAYMENT = "no_payment_token"
TOO_MANY_PENDING_REASON = "Too many orders from this agent are already waiting for your approval"
PREFLIGHT_ERROR_REASON = "Security checks could not be completed"


class Executor(Protocol):
    mode: str

    async def authorize(self, order_id: str) -> tuple[str, str]: ...
    async def capture(self, order_id: str, authorization_id: str) -> str: ...
    async def void(self, order_id: str, authorization_id: str) -> None: ...
    async def run_ai(self, ctx: PipelineContext) -> dict[str, StepRun]: ...


class OrderNotFound(Exception):
    pass


async def timed_ai_step(name: str, make_coro: Callable[[], Awaitable[dict]], *, retries: int) -> StepRun:
    t0 = time.perf_counter()
    err = "exception"
    attempts = 0
    for attempt in range(retries + 1):
        attempts = attempt + 1
        try:
            out = await asyncio.wait_for(make_coro(), timeout=limits.STEP_TIMEOUT_S)
        except TimeoutError:
            err = "timeout"
            log.warning("pipeline.step_timeout step=%s", name)
            break
        except Exception:
            err = "exception"
            log.warning("pipeline.step_exception step=%s attempt=%d", name, attempts)
            continue
        if not isinstance(out, dict):
            err = "bad_output"
            break
        return StepRun(out, ms_since(t0), attempts)
    return StepRun({"result": "error", "error": err}, ms_since(t0), attempts)


def _code(e: Exception, fallback: str) -> str:
    return (e.code if isinstance(e, PayPalError) else fallback)[:64]


async def run_pipeline(db, order_id: str, executor, *, allow_fixtures: bool = False) -> CheckoutOutcome:
    history: list[str] = []
    try:
        return await _run(db, order_id, executor, allow_fixtures, history)
    except OrderNotFound:
        raise
    except Exception:
        log.exception("pipeline.unexpected_error order_id=%s", order_id)
        return _recover(db, order_id, history)


def _recover(db, order_id: str, history: list[str]) -> CheckoutOutcome:
    db.rollback()
    order = db.get(Order, order_id)
    if order is None:
        raise  # the exception being handled by the caller
    now = utcnow()
    if order.status == "received":
        set_status(order, "failed", history)
        order.reasons = [CHECKOUT_FAILED_REASON]
    elif order.status in ("authorized", "checking"):
        if order.status == "authorized":
            set_status(order, "checking", history)
        ensure_approval(db, order, now)
        order.decision = "hold"
        order.reasons = [PIPELINE_HOLD_REASON]
        set_status(order, "pending_approval", history)
    db.commit()
    return outcome_from_order(order, history)


async def _run(db, order_id, ex, allow_fixtures, history) -> CheckoutOutcome:
    # Block 1: claim
    order = db.execute(
        select(Order).where(Order.id == order_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if order is None:
        db.rollback()
        raise OrderNotFound(order_id)
    started = db.execute(
        select(Check.id).where(Check.order_id == order_id, Check.step == "check_mandate").limit(1)
    ).first()
    if order.status != "received" or started is not None:
        db.commit()
        return outcome_from_order(order, history, already=True)

    # Block 2: verify + mandate (row lock held)
    vrow = db.execute(
        select(Check).where(Check.order_id == order_id, Check.step == "verify_agent")
        .order_by(Check.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    verify = {"result": vrow.result, "reason": (vrow.details_json or {}).get("reason")} if vrow else None
    t0 = time.perf_counter()
    intent = db.get(Intent, order.intent_id)
    agent = db.get(Agent, order.agent_id)
    mandate = select_mandate_for_agent(db, order.agent_id, order.merchant)
    spent = spent_in_period(db, mandate, exclude_order_id=order.id) if mandate is not None else Decimal("0")
    try:
        draft = OrderDraft.from_checkout(
            order.agent_id,
            {"intent_id": order.intent_id, "merchant": order.merchant, "cart": order.cart_json or []},
        )
        mandate_out = check_mandate(draft, mandate, spent, intent=intent).as_check_output()
    except ValueError:
        mandate_out = {"result": "fail", "reason": "invalid_cart",
                       "message": "Cart is empty or has invalid lines"}
    record_check(db, order.id, "check_mandate", mandate_out["result"], mandate_out, ms_since(t0))
    pre = decide(verify, mandate_out, None, None, None)
    if pre.decision == "reject":
        record_check(db, order.id, "decide", "fail", {"decision": "reject", "reasons": pre.reasons}, 0)
        record_skipped(db, order.id, ("authorize_payment", "scan_injection", "intent_diff",
                                      "graph_risk", "capture_or_void"), "rejected")
        order.decision = "reject"
        order.reasons = list(pre.reasons)
        set_status(order, "rejected", history)
        db.commit()
        build_proof_step(db, order.id)
        return outcome_from_order(order, history)
    db.commit()

    # Block 3: authorize
    t0 = time.perf_counter()
    try:
        pp_order_id, auth_id = await ex.authorize(order.id)
    except Exception as e:
        if _buyer_can_approve(e):
            if e.code != NO_SAVED_PAYMENT:
                log.warning("pipeline.saved_payment_failed order_id=%s code=%s; asking the buyer", order.id, e.code)
            try:
                return await _ask_buyer(db, order, ex.mode, history, t0)
            except Exception as e2:  # could not create the PayPal approval either
                db.rollback()
                e = e2
        code = _code(e, "authorize_failed")
        debug = e.debug_id if isinstance(e, PayPalError) else None
        record_check(db, order.id, "authorize_payment", "error",
                     {"mode": ex.mode, "error": code, "debug_id": debug}, ms_since(t0))
        record_skipped(db, order.id, ("scan_injection", "intent_diff", "graph_risk", "decide",
                                      "capture_or_void"), "payment_failed")
        order.reasons = [PAYMENT_FAILED_REASON]
        set_status(order, "failed", history)
        db.commit()
        build_proof_step(db, order.id)
        return outcome_from_order(order, history)
    order.paypal_order_id = pp_order_id
    order.authorization_id = auth_id
    record_check(db, order.id, "authorize_payment", "pass",
                 {"mode": ex.mode, "paypal_order_id": pp_order_id, "authorization_id": auth_id},
                 ms_since(t0))
    set_status(order, "authorized", history)
    db.commit()
    set_status(order, "checking", history)
    db.commit()
    return await _check_and_settle(db, order, ex, intent, mandate, agent, verify, mandate_out, auth_id,
                                   allow_fixtures, history)


def _buyer_can_approve(e: Exception) -> bool:
    """No saved PayPal account, or (in sandbox) the saved one was refused: the buyer can approve in PayPal."""
    if not isinstance(e, PayPalError):
        return False
    if e.code == NO_SAVED_PAYMENT:
        return True
    return paypal_service.paypal_mode() == "sandbox" and not e.retryable and e.code not in (
        "not_configured", "live_env_not_allowed", "auth_failed", "INVALID_CART", "INVALID_AMOUNT",
        "AMOUNT_MISMATCH", "CURRENCY_MISMATCH")


async def _ask_buyer(db, order, mode: str, history, t0) -> CheckoutOutcome:
    """No saved PayPal account yet: create a PayPal order the buyer approves in PayPal. The pipeline
    resumes from resume_after_payment once PayPal sends the buyer back."""
    base = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not base or base == "__FILL_ME__":
        raise PayPalError("not_configured")
    back = f"{base}/paypal/return?order_id={order.id}"
    pp_order_id, url = await asyncio.to_thread(paypal_service.create_checkout, order, back, f"{back}&cancelled=1")
    order.paypal_order_id = pp_order_id
    order.payer_action_url = url
    record_check(db, order.id, "authorize_payment", "flag",
                 {"mode": mode, "action": "buyer_approval", "paypal_order_id": pp_order_id}, ms_since(t0))
    set_status(order, "awaiting_payment", history)
    db.commit()
    return outcome_from_order(order, history)


async def resume_after_payment(db, order_id: str, executor, *, allow_fixtures: bool = False) -> CheckoutOutcome:
    """Run the checks and capture/void for an order the buyer just approved and authorized in PayPal."""
    history: list[str] = []
    try:
        order = db.execute(
            select(Order).where(Order.id == order_id).with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if order is None:
            db.rollback()
            raise OrderNotFound(order_id)
        if order.status != "authorized" or not order.authorization_id:
            db.commit()
            return outcome_from_order(order, history, already=True)
        latest = {}
        for c in db.execute(select(Check).where(Check.order_id == order_id).order_by(Check.created_at)).scalars():
            latest[c.step] = c
        v = latest.get("verify_agent")
        verify = {"result": v.result, "reason": (v.details_json or {}).get("reason")} if v else None
        m = latest.get("check_mandate")
        mandate_out = dict(m.details_json or {}) if m else {"result": "fail", "reason": "mandate_check_missing"}
        intent = db.get(Intent, order.intent_id)
        agent = db.get(Agent, order.agent_id)
        mandate = select_mandate_for_agent(db, order.agent_id, order.merchant)
        set_status(order, "checking", history)
        db.commit()
        return await _check_and_settle(db, order, executor, intent, mandate, agent, verify, mandate_out,
                                       order.authorization_id, allow_fixtures, history)
    except OrderNotFound:
        raise
    except Exception:
        log.exception("pipeline.resume_error order_id=%s", order_id)
        return _recover(db, order_id, history)


async def _preflight_gate(db, order, reasons: list[str], allow_fixtures: bool = False) -> tuple[str, list[str]]:
    """The 32 payment checks. They can only turn a capture into a hold, never anything into a capture."""
    t0 = time.perf_counter()
    try:
        result = await asyncio.to_thread(run_preflight, db, order, user_approved=False, allow_fixtures=allow_fixtures)
    except Exception:
        log.exception("pipeline.preflight_error order_id=%s", order.id)
        db.rollback()
        record_check(db, order.id, "preflight", "fail",
                     {"error": "preflight_error", "passed": 0, "total": TOTAL_CHECKS}, ms_since(t0))
        return "hold", reasons + [PREFLIGHT_ERROR_REASON]
    record_check(db, order.id, "preflight", "pass" if result["passed"] else "fail",
                 preflight_details(result), ms_since(t0))
    if result["passed"]:
        return "capture", reasons
    return "hold", reasons + result["failed"]


async def _check_and_settle(db, order, ex, intent, mandate, agent, verify, mandate_out, auth_id,
                            allow_fixtures, history) -> CheckoutOutcome:
    # Block 4: parallel AI checks
    ctx = build_context(db, order, intent, mandate, agent, allow_fixtures=allow_fixtures)
    runs = await ex.run_ai(ctx)
    inj = runs["scan_injection"].output
    diff = runs["intent_diff"].output
    graph = runs["graph_risk"].output
    for step, out, mapper in (("scan_injection", inj, injection_result),
                              ("intent_diff", diff, intent_diff_result),
                              ("graph_risk", graph, graph_result)):
        result, score = mapper(out)
        record_check(db, order.id, step, result, {**out, "attempts": runs[step].attempts},
                     runs[step].duration_ms, score)
    db.commit()

    # Block 5: decide (raw adapter outputs, not row results)
    t0 = time.perf_counter()
    d = decide(verify, mandate_out, inj, diff, graph)
    decision = d.decision if d.decision in ("capture", "void", "hold") else "void"
    reasons = list(d.reasons)
    if decision == "hold" and pending_approvals(db, order.agent_id, exclude_order_id=order.id) >= PENDING_APPROVALS_PER_AGENT:
        # Approval fatigue: don't queue yet another order for a human who already has a pile to review.
        decision = "void"
        reasons.append(TOO_MANY_PENDING_REASON)
    if decision == "capture":
        decision, reasons = await _preflight_gate(db, order, reasons, allow_fixtures)
    record_check(db, order.id, "decide", decision_result(decision),
                 {"decision": decision, "reasons": reasons}, ms_since(t0))
    order.decision = decision
    order.reasons = reasons
    db.commit()

    # Block 6: capture / void / hold
    t0 = time.perf_counter()
    if decision == "capture":
        try:
            cap = await ex.capture(order.id, auth_id)
            order.capture_id = cap
            record_check(db, order.id, "capture_or_void", "pass",
                         {"action": "capture", "capture_id": cap}, ms_since(t0))
            set_status(order, "captured", history)
        except Exception as e:
            voided = False
            try:
                await ex.void(order.id, auth_id)
                voided = True
            except Exception:
                pass
            record_check(db, order.id, "capture_or_void", "error",
                         {"action": "capture", "error": _code(e, "capture_failed"), "voided": voided},
                         ms_since(t0))
            set_status(order, "failed", history)
    elif decision == "void":
        try:
            await ex.void(order.id, auth_id)
            record_check(db, order.id, "capture_or_void", "pass", {"action": "void"}, ms_since(t0))
            set_status(order, "voided", history)
        except Exception as e:
            record_check(db, order.id, "capture_or_void", "error",
                         {"action": "void", "error": _code(e, "void_failed"), "voided": False},
                         ms_since(t0))
            set_status(order, "failed", history)
    else:
        appr = ensure_approval(db, order, utcnow())
        record_check(db, order.id, "capture_or_void", "flag",
                     {"action": "hold", "approval_id": appr.id, "expires_at": iso_z(appr.expires_at)},
                     ms_since(t0))
        set_status(order, "pending_approval", history)
    db.commit()

    # Block 7
    build_proof_step(db, order.id)
    return outcome_from_order(order, history)
