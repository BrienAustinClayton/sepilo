"""Customer emails about payments. Best-effort and never raises: a failed send is reported to the caller."""
from __future__ import annotations

import html
import logging

import httpx

from app.auth import RESEND_URL, _cfg, _is_local, web_origin

log = logging.getLogger("intentlock.notify")

ADDRESS_FIELDS = ("name", "line1", "line2", "city", "region", "postal_code", "country")
DISPUTE_LINE = "If you didn't ask for this, open the order and raise a dispute."


def _address_lines(address) -> list[str]:
    if not isinstance(address, dict):
        return []
    parts = [str(address.get(k)).strip() for k in ADDRESS_FIELDS if address.get(k)]
    return [p for p in parts if p]


def _items(order) -> list[tuple[str, str, str]]:
    out = []
    for line in order.cart_json or []:
        if not isinstance(line, dict):
            continue
        title = str(line.get("title") or line.get("product_id") or "Item")[:120]
        out.append((str(line.get("qty", 1)), title, str(line.get("unit_price", ""))))
    return out


def _bodies(user, order) -> tuple[str, str]:
    link = f"{web_origin()}/orders/{order.id}"
    amount = f"{order.total} {order.currency}"
    items = _items(order)
    address = _address_lines(order.shipping_address or user.shipping_address)
    text_items = "\n".join(f"  {q} x {t} @ {p}" for q, t, p in items)
    text = (
        f"Sepilo is about to pay {amount} to {order.merchant}.\n\n"
        f"Items:\n{text_items}\n\n"
        "Ship to:\n  " + "\n  ".join(address) + f"\n\nOpen the order: {link}\n\n{DISPUTE_LINE}\n"
    )
    html_items = "".join(
        f"<li>{html.escape(q)} &times; {html.escape(t)} @ {html.escape(p)}</li>" for q, t, p in items)
    html_address = "<br>".join(html.escape(a) for a in address)
    body = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;color:#111318">
<p style="font-size:15px;font-weight:600;margin:0 0 24px">Sepilo</p>
<p style="font-size:14px;margin:0 0 12px">Sepilo is about to pay <strong>{html.escape(amount)}</strong> to <strong>{html.escape(order.merchant)}</strong>.</p>
<ul style="font-size:14px;margin:0 0 16px;padding-left:20px">{html_items}</ul>
<p style="font-size:13px;color:#565d6b;margin:0 0 4px">Ship to</p>
<p style="font-size:14px;margin:0 0 16px">{html_address}</p>
<p style="font-size:14px;margin:0 0 16px"><a href="{html.escape(link)}">Open the order</a></p>
<p style="font-size:13px;color:#565d6b;margin:0">{DISPUTE_LINE}</p>
</div>"""
    return text, body


def send_payment_notice(user, order) -> bool:
    try:
        key = _cfg("RESEND_API_KEY")
        if not key:
            if _is_local():
                log.warning("notify.dev_payment_notice order_id=%s (RESEND_API_KEY unset; local dev only)", order.id)
                return True
            log.warning("notify.payment_notice_not_configured order_id=%s", order.id)
            return False
        if not user.email:
            return False
        text, body_html = _bodies(user, order)
        body = {
            "from": _cfg("RESEND_FROM") or "Sepilo <support@sepilo.space>",
            "to": [user.email],
            "subject": f"Sepilo is paying {order.total} {order.currency} to {order.merchant}",
            "text": text,
            "html": body_html,
        }
        r = httpx.post(RESEND_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=10)
        if r.status_code >= 300:
            log.warning("notify.payment_notice_failed order_id=%s status=%s", order.id, r.status_code)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("notify.payment_notice_failed order_id=%s error=%s", order.id, type(e).__name__)
        return False
