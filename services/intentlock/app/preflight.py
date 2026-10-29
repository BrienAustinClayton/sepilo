"""Payment preflight: 32 named checks that must all pass before an order is captured (paid).

Pure code, no LLM. It can only turn a capture into a hold: any failure sends the order to a human.
When the user approves a held order themselves (user_approved=True), the AI warnings (P26-P29) are
reported as "accepted" because they have reviewed them; every other check must still pass.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select

from app.intents import verify_intent_signature
from app.mandates import _is_active, merchant_allowed, select_mandate_for_agent, spent_in_period
from app.models import Agent, Check, Intent, Order, User
from app.notify import send_payment_notice
from app.product_truth import domain_of
from app.signing import to_utc, utcnow
from app.velocity import NOT_PAYMENT_ACTIONS, _limit

log = logging.getLogger("intentlock.preflight")

ORDER_HARD_CAP = Decimal("2500.00")
USER_DAILY_CAP = Decimal("5000.00")
INTENT_MAX_AGE = timedelta(hours=24)
DUPLICATE_WINDOW = timedelta(minutes=10)
CART_MAX_LINES = 20
CART_MAX_QTY = 20
RISK_FLAG_SCORE = 30
OPEN_ORDER_STATUSES = ("authorized", "checking", "pending_approval", "captured")
LAB_PAGES = Path(__file__).resolve().parents[3] / "data" / "lab" / "pages"
PRICE_RE = re.compile(r"^\d+\.\d{2}$")
CENT = Decimal("0.01")
UNCHECKED = "Could not be checked"


@dataclass
class _Ctx:
    db: object
    order: Order
    user_approved: bool
    now: object
    allow_fixtures: bool = False
    user: User | None = None
    agent: Agent | None = None
    intent: Intent | None = None
    mandate: object = None
    rows: dict = field(default_factory=dict)
    cart: list = field(default_factory=list)
    total: Decimal = Decimal("0.00")


def _load(db, order: Order, user_approved: bool, allow_fixtures: bool) -> _Ctx:
    ctx = _Ctx(db=db, order=order, user_approved=user_approved, now=utcnow(), allow_fixtures=allow_fixtures)
    ctx.user = db.get(User, order.user_id)
    ctx.agent = db.get(Agent, order.agent_id)
    ctx.intent = db.get(Intent, order.intent_id)
    ctx.mandate = select_mandate_for_agent(db, order.agent_id, order.merchant)
    for c in db.execute(select(Check).where(Check.order_id == order.id).order_by(Check.created_at, Check.id)).scalars():
        ctx.rows[c.step] = c
    ctx.cart = [l for l in (order.cart_json or []) if isinstance(l, dict)] if isinstance(order.cart_json, list) else []
    ctx.total = Decimal(str(order.total)).quantize(CENT)
    return ctx


def _row_passed(ctx: _Ctx, step: str) -> tuple[bool, str]:
    row = ctx.rows.get(step)
    if row is None:
        return False, "No result recorded"
    return row.result == "pass", f"Result: {row.result}"


def _money(v) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _p01(c): return _row_passed(c, "verify_agent")
def _p02(c): return (c.agent is not None and c.agent.revoked_at is None), "Agent missing or revoked"
def _p03(c): return (c.agent is not None and c.agent.user_id == c.order.user_id), "Agent belongs to another user"


def _p04(c):
    i = c.intent
    return (i is not None and i.user_id == c.order.user_id and i.agent_id == c.order.agent_id), "Request mismatch"


def _p05(c):
    i = c.intent
    return (i is not None and bool(i.signature) and verify_intent_signature(i)), "Request signature is missing or invalid"


def _p06(c):
    i = c.intent
    if i is None or i.signed_at is None:
        return False, "Request has no signing time"
    return to_utc(i.signed_at) >= c.now - INTENT_MAX_AGE, "Request was signed more than 24 hours ago"


def _p07(c): return _row_passed(c, "check_mandate")


def _p08(c):
    m = c.mandate
    return (m is not None and _is_active(m, c.now)), "No active spending rule for this agent and store"


def _p09(c):
    m = c.mandate
    return (m is not None and merchant_allowed(c.order.merchant, m.merchants or [])), "Store not allowed by the rule"


def _p10(c):
    m = c.mandate
    if m is None:
        return False, "No spending rule"
    allowed = {str(x).strip().lower() for x in (m.categories or [])}
    bad = [l for l in c.cart if l.get("category") and str(l["category"]).strip().lower() not in allowed]
    return not bad, "A cart category is not allowed by the rule"


def _p11(c):
    m = c.mandate
    if m is None:
        return False, "No spending rule"
    spent = spent_in_period(c.db, m, exclude_order_id=c.order.id)
    return spent + c.total <= Decimal(str(m.budget_amount)), "Over the rule's budget"


def _p12(c):
    m = c.mandate
    return (m is not None and c.order.currency == m.currency), "Currency differs from the rule"


def _p13(c): return (Decimal("0") < c.total <= ORDER_HARD_CAP), f"Total must be above 0 and at most {ORDER_HARD_CAP}"


def _p14(c):
    if not (1 <= len(c.cart) <= CART_MAX_LINES) or len(c.cart) != len(c.order.cart_json or []):
        return False, f"Cart must have 1 to {CART_MAX_LINES} lines"
    for l in c.cart:
        q = l.get("qty")
        if isinstance(q, bool) or not isinstance(q, int) or not (1 <= q <= CART_MAX_QTY):
            return False, f"Quantity must be 1 to {CART_MAX_QTY}"
        if not PRICE_RE.match(str(l.get("unit_price", ""))):
            return False, "Unit price is not a 2-decimal amount"
    return True, ""


def _p15(c):
    try:
        s = sum((Decimal(str(l["unit_price"])) * l["qty"] for l in c.cart), Decimal("0")).quantize(CENT)
    except (KeyError, TypeError, InvalidOperation, ValueError):
        return False, "Cart lines could not be added up"
    return s == c.total, "Line totals differ from the order total"


def _p16(c):
    approved = c.intent.approved_cart if c.intent is not None else None
    if not approved:
        return True, ""
    try:
        want = sorted(((str(a["product_id"]), int(a["qty"]), domain_of(a.get("merchant")), Decimal(str(a["unit_price"])))
                       for a in approved), key=lambda t: (t[0], t[1], t[3]))
        store = domain_of(c.order.merchant)
        got = sorted(((str(l["product_id"]), int(l["qty"]), store, Decimal(str(l["unit_price"]))) for l in c.cart),
                     key=lambda t: (t[0], t[1], t[3]))
    except (KeyError, TypeError, InvalidOperation, ValueError):
        return False, "Approved cart could not be read"
    if len(want) != len(got):
        return False, "Different number of lines than approved"
    for w, g in zip(want, got):
        if w[:3] != g[:3] or g[3] > w[3]:
            return False, "Cart differs from the one you approved"
    return True, ""


def _p17(c):
    n = c.db.execute(
        select(func.count()).select_from(Order)
        .where(Order.intent_id == c.order.intent_id, Order.id != c.order.id, Order.status.in_(OPEN_ORDER_STATUSES))
    ).scalar_one()
    return n == 0, "Another order exists for the same request"


def _p18(c):
    n = c.db.execute(
        select(func.count()).select_from(Order)
        .where(Order.user_id == c.order.user_id, Order.merchant == c.order.merchant, Order.total == c.order.total,
               Order.status == "captured", Order.id != c.order.id, Order.created_at >= c.now - DUPLICATE_WINDOW)
    ).scalar_one()
    return n == 0, "Same store and amount was just paid"


def _p19(c):
    n = c.db.execute(
        select(func.count()).select_from(Order)
        .where(Order.agent_id == c.order.agent_id, Order.created_at >= c.now - timedelta(days=1),
               Order.status.notin_(NOT_PAYMENT_ACTIONS))
    ).scalar_one()
    return n <= _limit("AGENT_ORDERS_PER_DAY"), "Agent reached its daily order limit"


def _p20(c):
    start = c.now.replace(hour=0, minute=0, second=0, microsecond=0)
    spent = Decimal(str(c.db.execute(
        select(func.coalesce(func.sum(Order.total), 0))
        .where(Order.user_id == c.order.user_id, Order.status == "captured", Order.id != c.order.id,
               Order.created_at >= start)
    ).scalar_one()))
    return spent + c.total <= USER_DAILY_CAP, f"Daily spending limit of {USER_DAILY_CAP} would be exceeded"


def _p21(c):
    u = c.user
    return (u is not None and bool(u.email) and u.email_verified_at is not None), "Email missing or not verified"


def _p22(c):
    a = c.user.shipping_address if c.user is not None else None
    return (isinstance(a, dict) and bool(a)), "No shipping address on file"


def _address(c) -> dict:
    a = c.user.shipping_address if c.user is not None else None
    return a if isinstance(a, dict) else {}


def _p23(c):
    a = _address(c)
    for k in ("name", "line1", "city", "postal_code"):
        if not (isinstance(a.get(k), str) and a[k].strip()):
            return False, f"Shipping address is missing {k}"
    country = a.get("country")
    return (isinstance(country, str) and len(country.strip()) == 2 and country.strip().isalpha()), \
        "Shipping country must be a 2-letter code"


def _p24(c):
    uc = c.user.country if c.user is not None else None
    if not uc:
        return True, ""
    ac = _address(c).get("country")
    return (isinstance(ac, str) and ac.strip().upper() == uc.strip().upper()), "Shipping country differs from your country"


def _p25(c): return (bool(c.order.authorization_id) and bool(c.order.paypal_order_id)), "No payment authorization"


def _ai(c: _Ctx, step: str, extra=None) -> tuple[str, str]:
    row = c.rows.get(step)
    if row is None or row.result == "skipped":
        return "fail", "No result recorded"
    problem = extra(row) if extra is not None else None
    if row.result == "pass" and problem is None:
        return "pass", ""
    if row.result in ("pass", "flag", "error") and c.user_approved:
        return "accepted", problem or f"Result: {row.result}; reviewed by you"
    return "fail", problem or f"Result: {row.result}"


def _p26(c): return _ai(c, "scan_injection")


def _p27(c): return _ai(c, "intent_diff")


def _risk_problem(row):
    try:
        return None if row.score is not None and Decimal(str(row.score)) < RISK_FLAG_SCORE else "Risk score is high or missing"
    except (InvalidOperation, ValueError):
        return "Risk score is unreadable"


def _p28(c): return _ai(c, "graph_risk", _risk_problem)


def _p29(c):
    return _ai(c, "intent_diff", lambda row: "Price anomaly flagged" if (row.details_json or {}).get("price_anomaly") else None)


def _lab_fixture(u: str) -> bool:
    p = Path(u)
    return u.endswith(".html") and str(p.resolve()) == u and p.is_relative_to(LAB_PAGES)


def _page_ok(c, u) -> bool:
    return isinstance(u, str) and (u.startswith("https://") or (c.allow_fixtures and _lab_fixture(u)))


def _p30(c):
    urls = c.order.page_urls or []
    ok = isinstance(urls, list) and all(_page_ok(c, u) for u in urls)
    return ok, "A store page is not HTTPS"


def _p31(c):
    if domain_of(c.order.merchant) is None:
        return False, "Store name is not a valid domain"
    return True, ""


CHECKS = (
    ("P01", "Agent signature verified", _p01),
    ("P02", "Agent is active", _p02),
    ("P03", "Agent belongs to the buyer", _p03),
    ("P04", "Request matches buyer and agent", _p04),
    ("P05", "Request is signed", _p05),
    ("P06", "Request signed within 24 hours", _p06),
    ("P07", "Spending rule check passed", _p07),
    ("P08", "An active spending rule covers this order", _p08),
    ("P09", "Store allowed by spending rule", _p09),
    ("P10", "Item categories allowed by spending rule", _p10),
    ("P11", "Within spending rule budget", _p11),
    ("P12", "Currency matches spending rule", _p12),
    ("P13", "Order total within the per-order limit", _p13),
    ("P14", "Cart is well formed", _p14),
    ("P15", "Line totals add up to the order total", _p15),
    ("P16", "Cart matches what you approved", _p16),
    ("P17", "No other open order for this request", _p17),
    ("P18", "Not a duplicate of a recent payment", _p18),
    ("P19", "Agent under its daily order limit", _p19),
    ("P20", "Within your daily spending limit", _p20),
    ("P21", "Verified email on file", _p21),
    ("P22", "Shipping address on file", _p22),
    ("P23", "Shipping address is complete", _p23),
    ("P24", "Shipping country matches your country", _p24),
    ("P25", "Payment authorization exists", _p25),
    ("P26", "No prompt injection found", _p26),
    ("P27", "Order matches your request", _p27),
    ("P28", "Store risk is low", _p28),
    ("P29", "No price anomaly", _p29),
    ("P30", "Store pages use HTTPS", _p30),
    ("P31", "Store domain is valid", _p31),
)
NOTICE_ID = "P32"
NOTICE_LABEL = "Payment notice emailed to you"
TOTAL_CHECKS = len(CHECKS) + 1


def _run_one(ctx: _Ctx, fn) -> tuple[str, str]:
    try:
        out = fn(ctx)
    except Exception:
        log.warning("preflight.check_error order_id=%s check=%s", ctx.order.id, fn.__name__.lstrip("_"))
        return "fail", UNCHECKED
    if isinstance(out[0], str):
        return out
    ok, detail = out
    return ("pass", "") if ok else ("fail", detail)


def run_preflight(db, order: Order, *, user_approved: bool, allow_fixtures: bool = False) -> dict:
    ctx = _load(db, order, user_approved, allow_fixtures)
    checks = []
    for cid, label, fn in CHECKS:
        status, detail = _run_one(ctx, fn)
        checks.append({"id": cid, "label": label, "status": status, "detail": detail})
    failed = [c["label"] for c in checks if c["status"] == "fail"]
    if failed:
        checks.append({"id": NOTICE_ID, "label": NOTICE_LABEL, "status": "fail", "detail": "not_sent"})
        return {"passed": False, "checks": checks, "failed": failed}
    sent = send_payment_notice(ctx.user, order)
    checks.append({"id": NOTICE_ID, "label": NOTICE_LABEL, "status": "pass" if sent else "fail",
                   "detail": "" if sent else "The email could not be sent"})
    if not sent:
        return {"passed": False, "checks": checks, "failed": [NOTICE_LABEL]}
    order.shipping_address = dict(ctx.user.shipping_address)
    return {"passed": True, "checks": checks, "failed": []}


def preflight_details(result: dict) -> dict:
    ok = sum(1 for c in result["checks"] if c["status"] in ("pass", "accepted"))
    return {"checks": result["checks"], "passed": ok, "total": TOTAL_CHECKS}
