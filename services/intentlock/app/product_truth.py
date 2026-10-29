"""Server-side truth for a checkout cart: every line is re-read from Channel3.

The agent's request body is untrusted (it may be confused by a poisoned page or a tampered tool response),
so price, store, category, title and page URL come from Channel3, never from the agent:

- the product must exist and be in stock at the claimed store (one of its Channel3 offers),
- the agent's unit price must equal that offer's current price,
- category, title and URL are replaced with Channel3's values (spending rules check the real category).

Web deals (product ids starting "web_", found by app/deals.py) are checked against the stored offer instead: its page is
re-read fresh through Firecrawl and must still show the stored price and PayPal.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.channel3 import Channel3Unavailable, get_product

log = logging.getLogger("intentlock.product_truth")

CENT = Decimal("0.01")
WEB_PREFIX = "web_"
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")


class CartNotVerified(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def domain_of(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    s = s[4:] if s.startswith("www.") else s
    return s if _DOMAIN_RE.fullmatch(s) else None


def _money(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v)).quantize(CENT)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() and d >= 0 else None


def _https(v: Any) -> str | None:
    return v if isinstance(v, str) and v.startswith("https://") and len(v) <= 2048 else None


def _top_category(raw: dict) -> str:
    cat = raw.get("category") if isinstance(raw.get("category"), dict) else {}
    path = cat.get("path") if isinstance(cat.get("path"), list) else []
    top = path[0] if path and isinstance(path[0], dict) else cat
    return str(top.get("slug") or "other")[:64]


def _web_offer(product_id: str, db=None):
    from app import deals

    return deals.load_offer(product_id, db)


def _web_recheck(offer) -> str | None:
    from app import deals

    return deals.recheck(offer)


def _verify_web_line(line: dict, pid: str, name: str, store: str, db) -> dict | str:
    """A web deal line, or the plain reason it can't be bought: it must be the stored offer, still on its page."""
    offer = _web_offer(pid, db)
    if offer is None:
        return f"{name} isn't a deal Sepilo found."
    if offer.merchant != store:
        return f"{name} isn't sold by {store}."
    real, claimed = _money(offer.price), _money(line.get("unit_price"))
    if claimed is None or claimed != real or str(line.get("currency") or "USD").upper() != offer.currency:
        return f"{name} costs ${real} at {store}, not ${claimed}."
    problem = _web_recheck(offer)
    if problem:
        return problem
    return {**line, "title": offer.title[:300], "category": offer.category or "other", "unit_price": f"{real:.2f}",
            "currency": offer.currency, "url": _https(offer.url)}


def verify_cart(merchant: str, lines: list[dict], db=None) -> tuple[str, list[dict], list[str]]:
    """Return (store, verified lines, page URLs) or raise CartNotVerified with plain reasons."""
    store = domain_of(merchant)
    if store is None:
        raise CartNotVerified([f"“{str(merchant)[:40]}” isn't a store Sepilo can verify."])
    out, pages, reasons = [], [], []
    for line in lines:
        pid = str(line.get("product_id") or "")
        name = str(line.get("title") or pid)[:60]
        if pid.startswith(WEB_PREFIX):
            verified = _verify_web_line(line, pid, name, store, db)
            if isinstance(verified, str):
                reasons.append(verified)
                continue
            if verified["url"] and verified["url"] not in pages:
                pages.append(verified["url"])
            out.append(verified)
            continue
        try:
            raw = get_product(pid, db=db, fresh=True)
        except httpx.HTTPStatusError as e:
            reasons.append(f"{name} isn't on Channel3 any more." if e.response.status_code == 404
                           else f"Couldn't re-check {name} with Channel3.")
            continue
        except Channel3Unavailable as e:
            reasons.append("Sepilo has used today's product-check allowance. Try again tomorrow."
                           if e.reason == "budget" else
                           f"Couldn't re-check {name} with Channel3 right now. Try again in a minute.")
            continue
        except Exception:
            log.warning("product_truth.lookup_failed product_id=%s", pid[:64])
            reasons.append(f"Couldn't re-check {name} with Channel3.")
            continue
        offers = [o for o in raw.get("offers") or [] if isinstance(o, dict) and domain_of(o.get("domain")) == store]
        if not offers:
            reasons.append(f"{name} isn't sold by {store} on Channel3.")
            continue
        offer = offers[0]
        if str(offer.get("availability") or "InStock") != "InStock":
            reasons.append(f"{name} is out of stock at {store}.")
            continue
        price_obj = offer.get("price") if isinstance(offer.get("price"), dict) else {}
        real = _money(price_obj.get("price"))
        claimed = _money(line.get("unit_price"))
        currency = str(price_obj.get("currency") or "USD").upper()
        if real is None or claimed is None or claimed != real or currency != str(line.get("currency") or "USD").upper():
            reasons.append(f"{name} costs ${real} at {store} now, not ${claimed}." if real is not None
                           else f"Channel3 has no price for {name} at {store}.")
            continue
        url = _https(offer.get("url"))
        if url and url not in pages:
            pages.append(url)
        out.append({**line, "title": str(raw.get("title") or line.get("title") or "")[:300],
                    "category": _top_category(raw), "unit_price": f"{real:.2f}", "currency": currency,
                    "url": url})
    if reasons:
        raise CartNotVerified(reasons)
    return store, out, pages[:10]


class ProductUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _current_web_offer(pid: str, db) -> dict[str, Any]:
    offer = _web_offer(pid, db)
    if offer is None:
        raise ProductUnavailable("This deal can't be checked any more.")
    problem = _web_recheck(offer)
    if problem:
        raise ProductUnavailable(problem)
    return {"merchant": offer.merchant, "price": f"{_money(offer.price):.2f}", "currency": offer.currency,
            "url": _https(offer.url), "title": offer.title[:300], "category": offer.category or "other"}


def current_offer(product: dict[str, Any], db=None) -> dict[str, Any]:
    """The store and price checkout will confirm for a product, read now from Channel3's product endpoint.

    Search results can list stores the product endpoint no longer has, so the cart takes its store and price
    from here: the suggested store when it is still listed in stock, otherwise the cheapest in-stock offer.
    Returns {"merchant", "price", "currency", "url", "title", "category"}.
    """
    pid = str(product.get("product_id") or "")
    if pid.startswith(WEB_PREFIX):
        return _current_web_offer(pid, db)
    try:
        raw = get_product(pid, db=db, fresh=True)
    except ValueError:
        raise ProductUnavailable("This product can't be checked.") from None
    except httpx.HTTPStatusError as e:
        raise ProductUnavailable("This product isn't on Channel3 any more." if e.response.status_code == 404
                                 else "Couldn't check this product with Channel3. Try again.") from None
    except Channel3Unavailable as e:
        raise ProductUnavailable("Sepilo has used today's product-check allowance. Try again tomorrow."
                                 if e.reason == "budget" else
                                 "Couldn't check this product with Channel3 right now. Try again in a minute.") from None
    offers = []
    for o in raw.get("offers") or []:
        if not isinstance(o, dict) or str(o.get("availability") or "InStock") != "InStock":
            continue
        store = domain_of(o.get("domain"))
        price_obj = o.get("price") if isinstance(o.get("price"), dict) else {}
        price = _money(price_obj.get("price"))
        currency = str(price_obj.get("currency") or "USD").upper()
        if store and price is not None and price > 0 and currency == "USD":
            offers.append((store, price, _https(o.get("url"))))
    if not offers:
        raise ProductUnavailable("No store has this product in stock on Channel3 right now.")
    preferred = domain_of(product.get("merchant"))
    store, price, url = next((o for o in offers if o[0] == preferred), min(offers, key=lambda o: o[1]))
    return {"merchant": store, "price": f"{price:.2f}", "currency": "USD", "url": url,
            "title": str(raw.get("title") or "")[:300], "category": _top_category(raw)}
