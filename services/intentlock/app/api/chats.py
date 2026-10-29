"""Shopping chat: conversations with a hosted agent that suggests products within its spending rules
and buys the one the user picks (as a signed purchase request checked by IntentLock)."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import deals, hosted_agents, runlog, velocity
from app.cart_review import review_cart
from app.product_truth import ProductUnavailable, current_offer
from app.untrusted import clean, guard_reply, had_hidden_chars, talks_to_agent
from app.auth import current_user
from app.db import get_db
from app.ids import new_id
from app.intents import create_intent
from app.mandates import CENT, _is_active, format_amount, spent_in_period
from app.models import Agent, AgentRun, Chat, ChatMessage, Mandate, Order, User
from app.service_errors import ServiceError
from app.signing import iso_z, utcnow

router = APIRouter(prefix="/me/chats", tags=["chats"])

HISTORY_TURNS = 8
MAX_PRODUCTS = 6
PRICE_RE = re.compile(r"^\d{1,9}\.\d{2}$")


def _not_found(what: str) -> HTTPException:
    return HTTPException(404, detail={"error": "not_found", "reason": f"{what} not found"})


def _own_chat(db: Session, user: User, chat_id: str) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise _not_found("chat")
    return chat


def agent_rules(db: Session, agent_id: str) -> list[dict[str, Any]]:
    now = utcnow()
    out = []
    for m in db.execute(select(Mandate).where(Mandate.agent_id == agent_id)).scalars():
        if not _is_active(m, now):
            continue
        remaining = max(Decimal(m.budget_amount) - spent_in_period(db, m, now), Decimal("0")).quantize(CENT)
        out.append({
            "id": m.id, "categories": sorted(m.categories or []), "merchants": sorted(m.merchants or []),
            "budget": format_amount(m.budget_amount), "remaining": format_amount(remaining),
            "period": m.budget_period, "currency": m.currency,
        })
    return out


def chat_rules(db: Session, chat: Chat) -> list[dict[str, Any]]:
    """The rules a chat shops under: the one the user picked, or all the agent's active rules
    (also when the picked rule has since ended)."""
    rules = agent_rules(db, chat.agent_id)
    return [r for r in rules if r["id"] == chat.mandate_id] or rules


def _check_rule(db: Session, agent_id: str, mandate_id: str) -> None:
    m = db.get(Mandate, mandate_id)
    if m is None or m.agent_id != agent_id:
        raise _not_found("spending rule")
    if not _is_active(m, utcnow()):
        raise HTTPException(409, detail={"error": "rule_inactive", "reason": "That spending rule has ended. Pick another one."})


def _clean_url(v: Any, limit: int) -> Optional[str]:
    return v[:limit] if isinstance(v, str) and v.startswith("https://") else None


def _clean_products(raw: Any) -> list[dict[str, Any]]:
    out = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict) or not isinstance(p.get("product_id"), str):
            continue
        price = str(p.get("price", ""))
        if not PRICE_RE.match(price):
            continue
        if any(talks_to_agent(p.get(k)) or had_hidden_chars(p.get(k)) for k in ("title", "brand")):
            runlog.emit("chat.listing_dropped", product_id=str(p["product_id"])[:64], reason="agent_directed_text")
            continue
        out.append({
            "product_id": p["product_id"][:128],
            "title": clean(p.get("title"), 200),
            "brand": clean(p["brand"], 80) if p.get("brand") else None,
            "price": price,
            "currency": str(p.get("currency") or "USD")[:3],
            "merchant": str(p.get("merchant") or "")[:64],
            "category": str(p.get("category") or "")[:64],
            "category_title": str(p["category_title"])[:64] if p.get("category_title") else None,
            "image": _clean_url(p.get("image"), 1000),
            "url": _clean_url(p.get("url"), 2048),
        })
        if len(out) >= MAX_PRODUCTS:
            break
    return out


def _message_view(m: ChatMessage, runs: dict[str, dict]) -> dict[str, Any]:
    return {
        "id": m.id, "role": m.role, "content": m.content, "products": m.products or [],
        "created_at": iso_z(m.created_at), "run": runs.get(m.run_id) if m.run_id else None,
    }


def _runs_for(db: Session, messages: list[ChatMessage]) -> dict[str, dict]:
    ids = [m.run_id for m in messages if m.run_id]
    if not ids:
        return {}
    runs = db.execute(select(AgentRun).where(AgentRun.id.in_(ids))).scalars().all()
    order_ids = [r.order_id for r in runs if r.order_id]
    orders = {o.id: o for o in db.execute(select(Order).where(Order.id.in_(order_ids))).scalars()} if order_ids else {}
    return {r.id: hosted_agents.run_to_dict(r, orders.get(r.order_id)) for r in runs}


def _agent_view(a: Optional[Agent]) -> Optional[dict[str, Any]]:
    if a is None:
        return None
    return {"id": a.id, "name": a.name, "managed": bool(a.managed), "kind": a.kind,
            "active": a.revoked_at is None}


def _add(db: Session, chat: Chat, role: str, content: str, **extra) -> ChatMessage:
    m = ChatMessage(id=new_id("msg"), chat_id=chat.id, role=role, content=content[:4000],
                    created_at=utcnow(), **extra)
    db.add(m)
    chat.updated_at = m.created_at
    return m


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@router.get("")
def list_chats(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    chats = db.execute(
        select(Chat).where(Chat.user_id == user.id).order_by(Chat.updated_at.desc()).limit(100)
    ).scalars().all()
    if not chats:
        return []
    last = {}
    for m in db.execute(
        select(ChatMessage).where(ChatMessage.chat_id.in_([c.id for c in chats])).order_by(ChatMessage.created_at)
    ).scalars():
        last[m.chat_id] = m
    return [{"id": c.id, "title": c.title, "agent_id": c.agent_id, "updated_at": iso_z(c.updated_at),
             "preview": (last[c.id].content[:120] if c.id in last else "")} for c in chats]


class ChatCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: Optional[str] = Field(default=None, max_length=64)
    mandate_id: Optional[str] = Field(default=None, max_length=64)
    agent_kind: Optional[Literal["channel3", "deals"]] = None


@router.post("", status_code=201)
def create_chat(body: ChatCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.agent_id:
        agent = db.get(Agent, body.agent_id)
        if agent is None or agent.user_id != user.id:
            raise _not_found("agent")
    else:
        hosted_agents.ensure_default_agents(db, user.id)
        agent = db.execute(
            select(Agent).where(Agent.user_id == user.id, Agent.managed.is_(True), Agent.revoked_at.is_(None),
                                Agent.kind == (body.agent_kind or "channel3"))
            .order_by(Agent.created_at.desc())
        ).scalars().first()
    if agent is None or not agent.managed or agent.revoked_at is not None:
        raise HTTPException(409, detail={"error": "no_hosted_agent",
                                         "reason": "That Sepilo agent is disconnected. Reconnect it on the Agents page."})
    if body.mandate_id:
        _check_rule(db, agent.id, body.mandate_id)
    now = utcnow()
    chat = Chat(id=new_id("cht"), user_id=user.id, agent_id=agent.id, mandate_id=body.mandate_id,
                title="New chat", created_at=now, updated_at=now)
    db.add(chat)
    db.commit()
    return {"id": chat.id, "title": chat.title, "agent_id": agent.id, "updated_at": iso_z(now), "preview": ""}


def _thread_view(db: Session, chat: Chat) -> dict[str, Any]:
    msgs = db.execute(
        select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.created_at)
    ).scalars().all()
    runs = _runs_for(db, msgs)
    options = agent_rules(db, chat.agent_id)
    picked = next((r["id"] for r in options if r["id"] == chat.mandate_id), None)
    rules = [r for r in options if r["id"] == picked] or options
    return {
        "id": chat.id, "title": chat.title, "agent": _agent_view(db.get(Agent, chat.agent_id)),
        "rule_id": picked, "rule_options": options, "rules": rules,
        "messages": [_message_view(m, runs) for m in msgs], "cart": _cart_view(chat, rules),
    }


@router.get("/{chat_id}")
def get_chat(chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _thread_view(db, _own_chat(db, user, chat_id))


class ChatUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mandate_id: Optional[str] = Field(default=None, max_length=64)  # null = shop under all the agent's rules
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)


@router.patch("/{chat_id}")
def update_chat(chat_id: str, body: ChatUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Rename the chat and/or switch the spending rule it shops under (only the fields sent change)."""
    chat = _own_chat(db, user, chat_id)
    sent = body.model_fields_set
    if "mandate_id" in sent:
        if body.mandate_id:
            _check_rule(db, chat.agent_id, body.mandate_id)
        chat.mandate_id = body.mandate_id
    if "title" in sent and body.title:
        chat.title = clean(body.title, 120)
        chat.updated_at = utcnow()
    db.commit()
    return _thread_view(db, chat)


@router.delete("/{chat_id}")
def delete_chat(chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    chat = _own_chat(db, user, chat_id)
    db.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat.id))
    db.delete(chat)
    db.commit()
    return {"ok": True}


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=1000)


def _history(db: Session, chat: Chat) -> list[dict[str, str]]:
    rows = db.execute(
        select(ChatMessage).where(ChatMessage.chat_id == chat.id)
        .order_by(ChatMessage.created_at.desc()).limit(HISTORY_TURNS)
    ).scalars().all()
    out = []
    for m in reversed(rows):
        text = m.content[:600]
        if m.products:
            text += " [shown: " + "; ".join(f"{p['title'][:60]} ${p['price']} at {p['merchant']}" for p in m.products[:6]) + "]"
        out.append({"role": m.role, "content": text})
    return out


@router.post("/{chat_id}/messages")
def send_message(chat_id: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    chat = _own_chat(db, user, chat_id)
    velocity.check_chat_rate(db, user.id)
    history = _history(db, chat)
    mine = _add(db, chat, "user", body.content)
    if chat.title == "New chat":
        chat.title = body.content[:60] + ("…" if len(body.content) > 60 else "")
    db.commit()

    agent = db.get(Agent, chat.agent_id)
    rules = chat_rules(db, chat)
    if agent is None or not agent.managed or agent.revoked_at is not None:
        reply = _add(db, chat, "assistant", "This chat's agent is disconnected. Start a new chat with an active hosted agent.")
    elif not rules:
        reply = _add(db, chat, "assistant",
                     "Your agent has no active spending rule yet, so it can't buy anything. "
                     "Add one under Spending rules (categories, stores and a budget) and ask again.")
    else:
        try:
            data = (deals.suggest(db, user.id, body.content, history, rules) if agent.kind == "deals"
                    else hosted_agents.suggest(agent.id, body.content, history, rules))
            products = _clean_products(data.get("products"))
            text = guard_reply(data.get("reply")) or (
                "Here's what I found." if products else "I couldn't find anything that fits.")
            reply = _add(db, chat, "assistant", text, products=products or None)
        except hosted_agents.HostedAgentError as e:
            reply = _add(db, chat, "assistant", e.message)
    db.commit()
    return {"messages": [_message_view(mine, {}), _message_view(reply, {})], "title": chat.title}


MAX_CART_LINES = 20


def _cart_view(chat: Chat, rules: list[dict[str, Any]]) -> dict[str, Any]:
    lines = list(chat.cart or [])
    total = sum((Decimal(l["price"]) * l["qty"] for l in lines), Decimal("0")).quantize(CENT)
    issues: list[str] = []
    for l in lines:
        fits = [r for r in rules if l["category"] in r["categories"]
                and ("*" in r["merchants"] or l["merchant"] in r["merchants"])]
        if not fits:
            issues.append(f"{l['title'][:60]} isn't allowed by your spending rules (category or store).")
    left = max((Decimal(r["remaining"]) for r in rules), default=Decimal("0"))
    if lines and total > left:
        issues.append(f"The cart total ${format_amount(total)} is more than the ${format_amount(left)} your rules have left.")
    if lines and not rules:
        issues.append("Your agent has no active spending rule.")
    return {"items": lines, "total": format_amount(total), "count": sum(l["qty"] for l in lines),
            "currency": "USD", "stores": len({l["merchant"] for l in lines}), "issues": issues}


class CartAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=128)
    qty: int = Field(default=1, ge=1, le=20)


@router.post("/{chat_id}/cart")
def add_to_cart(chat_id: str, body: CartAdd, user: User = Depends(current_user), db: Session = Depends(get_db)):
    chat = _own_chat(db, user, chat_id)
    shown = db.get(ChatMessage, body.message_id)
    if shown is None or shown.chat_id != chat.id or shown.role != "assistant":
        raise _not_found("message")
    product = next((p for p in (shown.products or []) if p.get("product_id") == body.product_id), None)
    if product is None:
        raise _not_found("product")
    lines = [dict(l) for l in chat.cart or []]  # copies: JSONB changes are only saved when the value differs
    line = next((l for l in lines if l["product_id"] == body.product_id), None)
    notice = None
    if line is not None:
        line["qty"] = min(line["qty"] + body.qty, 20)
    else:
        if len(lines) >= MAX_CART_LINES:
            raise HTTPException(409, detail={"error": "cart_full", "reason": "Your cart is full. Check out or remove something first."})
        # The cart holds the store and price checkout will confirm (Channel3's product read), not the search card's.
        try:
            offer = current_offer(product)
        except ProductUnavailable as e:
            raise HTTPException(409, detail={"error": "product_unavailable", "reason": e.reason})
        if offer["merchant"] != product.get("merchant"):
            notice = (f"{product.get('merchant')} no longer lists it on Channel3, so it was added from "
                      f"{offer['merchant']} at ${offer['price']}.")
        elif offer["price"] != product.get("price"):
            notice = f"The price is now ${offer['price']} at {offer['merchant']}."
        lines.append({**product, "merchant": offer["merchant"], "price": offer["price"],
                      "url": offer["url"] or product.get("url"), "category": offer["category"] or product.get("category"),
                      "qty": body.qty})
    chat.cart = lines
    chat.updated_at = utcnow()
    db.commit()
    return {**_cart_view(chat, chat_rules(db, chat)), "notice": notice}


class CartQty(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qty: int = Field(ge=0, le=20)


@router.patch("/{chat_id}/cart/{product_id}")
def update_cart(chat_id: str, product_id: str, body: CartQty, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    chat = _own_chat(db, user, chat_id)
    lines = list(chat.cart or [])
    if not any(l["product_id"] == product_id for l in lines):
        raise _not_found("cart item")
    chat.cart = [({**l, "qty": body.qty} if l["product_id"] == product_id else l)
                 for l in lines if body.qty > 0 or l["product_id"] != product_id]
    db.commit()
    return _cart_view(chat, chat_rules(db, chat))


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False  # the user saw the cart check's warnings and still wants to buy


@router.post("/{chat_id}/checkout")
def checkout_cart(chat_id: str, background: BackgroundTasks, body: Optional[CheckoutIn] = None,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The user's approval: one signed purchase request per store, listing exactly the approved items.
    The cart is checked first (rules, Channel3, listing text, Jev); nothing is bought if it's blocked."""
    chat = _own_chat(db, user, chat_id)
    if not user.shipping_address:
        raise HTTPException(409, detail={"error": "address_required", "reason": "Add a shipping address before buying."})
    lines = list(chat.cart or [])
    if not lines:
        raise HTTPException(409, detail={"error": "cart_empty", "reason": "Your cart is empty."})
    agent = db.get(Agent, chat.agent_id)
    if agent is None or not agent.managed or agent.revoked_at is not None:
        raise HTTPException(409, detail={"error": "agent_unavailable", "reason": "This chat's agent is disconnected."})
    velocity.check_cart_checkout_rate(db, user.id)
    view = _cart_view(chat, chat_rules(db, chat))

    recent = db.execute(
        select(ChatMessage).where(ChatMessage.chat_id == chat.id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.desc()).limit(3)
    ).scalars().all()
    asked = recent[0] if recent else None
    review = review_cart("\n".join(m.content for m in reversed(recent)), lines, view["issues"])
    runlog.emit("chat.cart_review", chat_id=chat.id, decision=review["decision"],
                checks={c["key"]: c["status"] for c in review["checks"]})
    if review["decision"] == "block":
        reason = " ".join(c["detail"] for c in review["checks"] if c["status"] == "block" and c["detail"])
        raise HTTPException(409, detail={"error": "cart_blocked", "reason": reason or "This cart can't be bought.",
                                         "review": review})
    if review["decision"] == "confirm" and not (body and body.confirm):
        raise HTTPException(409, detail={"error": "needs_confirmation", "reason": "Check the warnings before buying.",
                                         "review": review})
    stores: dict[str, list[dict]] = {}
    for l in lines:
        stores.setdefault(l["merchant"], []).append(l)
    messages, run_ids = [], []
    for merchant, group in stores.items():
        listing = "; ".join(f"{l['qty']} × {l['title']} at ${l['price']}" for l in group)
        request_text = (f"{asked.content if asked else ''}\n\nI approved this cart from {merchant}: {listing}.").strip()[:2000]
        try:
            intent = create_intent(db, user_id=user.id, agent_id=agent.id, request_text=request_text,
                                   approved_cart=[{"product_id": l["product_id"], "qty": l["qty"],
                                                   "unit_price": l["price"], "merchant": merchant} for l in group])
        except ServiceError as e:
            raise HTTPException(e.status_code, detail={"error": e.error, "reason": e.reason})
        run = hosted_agents.start_run(db, intent.id, user.id, agent.id,
                                      items=[{"product_id": l["product_id"], "qty": l["qty"]} for l in group])
        total = sum((Decimal(l["price"]) * l["qty"] for l in group), Decimal("0")).quantize(CENT)
        count = sum(l["qty"] for l in group)
        msg = _add(db, chat, "assistant",
                   f"Buying {count} item{'s' if count > 1 else ''} from {merchant} for ${format_amount(total)}. "
                   "Sepilo checks the order against your request and rules before anything is paid.",
                   intent_id=intent.id, run_id=run.id)
        messages.append((msg, run))
        run_ids.append(run.id)
    chat.cart = []
    db.commit()
    for rid in run_ids:
        background.add_task(hosted_agents.execute_run, rid)
    return {"messages": [_message_view(m, {r.id: hosted_agents.run_to_dict(r)}) for m, r in messages],
            "cart": _cart_view(chat, chat_rules(db, chat)), "review": review}
