"""Real PayPal Sandbox implementation. Loaded lazily by service._impl() when PAYPAL_MODE=sandbox.

Never log credentials, tokens or response bodies. SDK exceptions are mapped to
PayPalError and re-raised with `from None` (their __str__ includes the body).
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from paypalserversdk.models.address import Address  # noqa: F401  (re-exported for the spike)
from paypalserversdk.models.amount_breakdown import AmountBreakdown
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.capture_request import CaptureRequest
from paypalserversdk.models.card_request import CardRequest
from paypalserversdk.models.card_stored_credential import CardStoredCredential
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.experience_context_shipping_preference import (
    ExperienceContextShippingPreference,
)
from paypalserversdk.models.item_category import ItemCategory
from paypalserversdk.models.item_request import ItemRequest
from paypalserversdk.models.money import Money
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.payment_initiator import PaymentInitiator
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.payment_token_request import PaymentTokenRequest
from paypalserversdk.models.payment_token_request_payment_source import (
    PaymentTokenRequestPaymentSource,
)
from paypalserversdk.models.paypal_payment_token_customer_type import (
    PaypalPaymentTokenCustomerType,
)
from paypalserversdk.models.paypal_payment_token_usage_type import PaypalPaymentTokenUsageType
from paypalserversdk.models.paypal_wallet import PaypalWallet
from paypalserversdk.models.paypal_wallet_stored_credential import PaypalWalletStoredCredential
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
from paypalserversdk.models.refund_request import RefundRequest
from paypalserversdk.models.setup_token_request import SetupTokenRequest
from paypalserversdk.models.setup_token_request_payment_source import (
    SetupTokenRequestPaymentSource,
)
from paypalserversdk.models.stored_payment_source_payment_type import (
    StoredPaymentSourcePaymentType,
)
from paypalserversdk.models.stored_payment_source_usage_type import StoredPaymentSourceUsageType
from paypalserversdk.models.usage_pattern import UsagePattern
from paypalserversdk.models.vault_experience_context import VaultExperienceContext
from paypalserversdk.models.vault_paypal_wallet_request import VaultPaypalWalletRequest
from paypalserversdk.models.vault_token_request import VaultTokenRequest
from paypalserversdk.models.vault_token_request_type import VaultTokenRequestType

from app.paypal.service import PayPalError

log = logging.getLogger("intentlock.paypal")

SEND_STORED_CREDENTIAL: bool = True
ALREADY_CAPTURED: frozenset[str] = frozenset({"AUTHORIZATION_ALREADY_CAPTURED", "PREVIOUSLY_CAPTURED"})
ALREADY_VOIDED: frozenset[str] = frozenset(
    {"PREVIOUSLY_VOIDED", "AUTHORIZATION_VOIDED", "AUTHORIZATION_ALREADY_VOIDED"}
)
SPIKE_TOKEN_PATH: Path = Path(__file__).resolve().parents[4] / "data" / "seed" / ".spike_token"
CAPTURE_RAW: bool = False
RAW_LOG: list[tuple[str, int, str]] = []

CENT = Decimal("0.01")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CODE_RE = re.compile(r"[^A-Za-z0-9_]")
_CUR_RE = re.compile(r"^[A-Z]{3}$")
PLACEHOLDER_PREFIXES = ("tok_", "MOCK-")
MAX_LINES = 100


@dataclass(frozen=True)
class VaultRef:
    kind: str  # "paypal" | "card"
    id: str


@dataclass
class AuthResult:
    paypal_order_id: str
    authorization_id: str
    create_status: str
    authorize_called: bool
    authorization_status: str


# ---------------------------------------------------------------- errors

def _code(raw) -> str:
    s = _CODE_RE.sub("", str(raw or ""))[:64]
    return s or "paypal_error"


def _retryable(status: int | None) -> bool:
    return status is not None and (status in (408, 409, 429) or status >= 500)


def _map_exc(e: Exception) -> PayPalError:
    from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
    import requests
    from paypalserversdk.exceptions.api_exception import ApiException
    from paypalserversdk.exceptions.error_exception import ErrorException

    if isinstance(e, PayPalError):
        return e
    if isinstance(e, ErrorException):
        issue = None
        details = getattr(e, "details", None) or []
        if details and getattr(details[0], "issue", None):
            issue = details[0].issue
        code = issue or getattr(e, "name", None) or f"HTTP_{e.response_code}"
        return PayPalError(_code(code), getattr(e, "debug_id", None), _retryable(e.response_code))
    if isinstance(e, ApiException):
        name = debug = None
        issue = None
        try:
            d = json.loads(e.response.text or "{}")
            if isinstance(d, dict):
                name, debug = d.get("name"), d.get("debug_id")
                det = d.get("details")
                if isinstance(det, list) and det and isinstance(det[0], dict):
                    issue = det[0].get("issue")
        except (ValueError, AttributeError):
            pass
        return PayPalError(
            _code(issue or name or f"HTTP_{e.response_code}"),
            debug if isinstance(debug, str) else None,
            _retryable(e.response_code),
        )
    if isinstance(e, AuthValidationException):
        return PayPalError("auth_failed", None, False)
    if isinstance(e, requests.exceptions.RequestException):
        return PayPalError("network_error", None, True)
    return PayPalError("paypal_unexpected", None, False)


def _call(op: str, fn):
    from app.paypal.client import get_client

    client = get_client()
    try:
        resp = fn(client)
    except Exception as e:  # noqa: BLE001
        err = _map_exc(e)
        log.warning(
            "paypal.error op=%s code=%s debug_id=%s retryable=%s",
            op, err.code, err.debug_id, err.retryable,
        )
        raise err from None
    if CAPTURE_RAW:
        RAW_LOG.append((op, resp.status_code, resp.text or ""))
        del RAW_LOG[:-50]
    if resp.is_error():
        raise PayPalError(f"HTTP_{resp.status_code}", None, _retryable(resp.status_code))
    return resp


# ---------------------------------------------------------------- vault ref

def parse_vault_ref(raw):
    s = raw.strip() if isinstance(raw, str) else ""
    if not s or s.startswith(PLACEHOLDER_PREFIXES):
        return None
    kind, vid = ("card", s[5:]) if s.startswith("card:") else ("paypal", s)
    return VaultRef(kind, vid) if _ID_RE.fullmatch(vid) else None


def _fallback_vault():
    ref = parse_vault_ref(os.environ.get("PAYPAL_SANDBOX_VAULT_ID"))
    if ref:
        return ref
    try:
        d = json.loads(SPIKE_TOKEN_PATH.read_text())
        vid, src = d.get("vault_id"), d.get("source", "paypal")
        return parse_vault_ref(f"card:{vid}" if src == "card" else vid)
    except (OSError, ValueError, AttributeError):
        return None


def resolve_vault(order):
    user = getattr(order, "user", None)
    ref = parse_vault_ref(getattr(user, "paypal_payment_token", None)) or _fallback_vault()
    if ref is None:
        raise PayPalError("no_payment_token")
    return ref


# ---------------------------------------------------------------- order build

def _item_name(line: dict) -> str:
    t = line.get("title")
    if not isinstance(t, str) or not t.strip():
        t = str(line.get("product_id") or "Item")
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp"))
    t = " ".join(t.split()).strip("\"'")
    return t[:127].strip() or "Item"


def build_order_request(order, vault: VaultRef):
    cur = str(order.currency or "").upper()
    if not _CUR_RE.fullmatch(cur):
        raise PayPalError("CURRENCY_MISMATCH")
    lines = order.cart_json
    if not isinstance(lines, list) or not lines or len(lines) > MAX_LINES:
        raise PayPalError("INVALID_CART")
    items = []
    item_total = Decimal("0")
    for line in lines:
        if not isinstance(line, dict):
            raise PayPalError("INVALID_CART")
        qty = line.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or not (1 <= qty <= 9999):
            raise PayPalError("INVALID_CART")
        try:
            unit = Decimal(str(line.get("unit_price")))
        except (InvalidOperation, ValueError):
            raise PayPalError("INVALID_AMOUNT") from None
        if not unit.is_finite() or unit < 0 or unit != unit.quantize(CENT):
            raise PayPalError("INVALID_AMOUNT")
        lc = str(line.get("currency") or cur).upper()
        if lc != cur:
            raise PayPalError("CURRENCY_MISMATCH")
        kw = {}
        if line.get("product_id"):
            kw["sku"] = str(line["product_id"])[:127]
        items.append(
            ItemRequest(
                name=_item_name(line),
                unit_amount=Money(currency_code=cur, value=f"{unit:.2f}"),
                quantity=str(qty),
                category=ItemCategory.PHYSICAL_GOODS,
                **kw,
            )
        )
        item_total += unit * qty
    if item_total <= 0:
        raise PayPalError("INVALID_AMOUNT")
    try:
        total = Decimal(str(order.total))
    except (InvalidOperation, ValueError):
        raise PayPalError("INVALID_AMOUNT") from None
    if not total.is_finite() or total != item_total:
        raise PayPalError("AMOUNT_MISMATCH")

    if vault.kind == "paypal":
        sc = (
            PaypalWalletStoredCredential(
                payment_initiator=PaymentInitiator.MERCHANT,
                usage=StoredPaymentSourceUsageType.SUBSEQUENT,
                usage_pattern=UsagePattern.IMMEDIATE,
            )
            if SEND_STORED_CREDENTIAL
            else None
        )
        kw = {"stored_credential": sc} if sc is not None else {}
        ps = PaymentSource(paypal=PaypalWallet(vault_id=vault.id, **kw))
    else:
        sc = (
            CardStoredCredential(
                payment_initiator=PaymentInitiator.MERCHANT,
                payment_type=StoredPaymentSourcePaymentType.UNSCHEDULED,
                usage=StoredPaymentSourceUsageType.SUBSEQUENT,
            )
            if SEND_STORED_CREDENTIAL
            else None
        )
        kw = {"stored_credential": sc} if sc is not None else {}
        ps = PaymentSource(card=CardRequest(vault_id=vault.id, **kw))

    return OrderRequest(
        intent=CheckoutPaymentIntent.AUTHORIZE,
        purchase_units=[
            PurchaseUnitRequest(
                amount=AmountWithBreakdown(
                    currency_code=cur,
                    value=f"{item_total:.2f}",
                    breakdown=AmountBreakdown(
                        item_total=Money(currency_code=cur, value=f"{item_total:.2f}")
                    ),
                ),
                items=items,
                custom_id=str(order.id)[:127],
                description=f"Sepilo order {order.id}"[:127],
            )
        ],
        payment_source=ps,
    )


# ---------------------------------------------------------------- authorize

def _first_auth(o):
    for pu in getattr(o, "purchase_units", None) or []:
        pays = getattr(pu, "payments", None)
        for a in getattr(pays, "authorizations", None) or []:
            if getattr(a, "id", None):
                return a
    return None


def authorize_detailed(order, vault=None) -> AuthResult:
    if not isinstance(getattr(order, "id", None), str) or not _ID_RE.fullmatch(order.id):
        raise PayPalError("INVALID_CART")
    vault = vault or resolve_vault(order)
    body = build_order_request(order, vault)  # before any HTTP
    rid = order.id
    created = _call(
        "create_order",
        lambda c: c.orders.create_order(
            {"body": body, "paypal_request_id": rid, "prefer": "return=representation"}
        ),
    ).body
    status = str(getattr(created, "status", "") or "").upper()
    called = False
    if status == "COMPLETED":
        src = created
    elif status in ("CREATED", "APPROVED"):
        called = True
        try:
            src = _call(
                "authorize_order",
                lambda c: c.orders.authorize_order(
                    {
                        "id": created.id,
                        "paypal_request_id": f"{rid}-auth",
                        "prefer": "return=representation",
                    }
                ),
            ).body
        except PayPalError as e:
            if e.code != "ORDER_ALREADY_AUTHORIZED":
                raise
            src = _call("get_order", lambda c: c.orders.get_order({"id": created.id})).body
    elif status == "PAYER_ACTION_REQUIRED":
        raise PayPalError("PAYER_ACTION_REQUIRED")
    else:
        raise PayPalError(_code(f"ORDER_{status or 'UNKNOWN'}"))
    auth = _first_auth(src)
    if auth is None:
        raise PayPalError("AUTHORIZATION_MISSING")
    ast = str(getattr(auth, "status", "") or "").upper()
    if ast != "CREATED":
        if ast == "PENDING":
            try:
                void(auth.id, request_id=f"{rid}-void-pending")
            except PayPalError:
                pass
        raise PayPalError(_code(f"AUTHORIZATION_{ast or 'UNKNOWN'}"))
    return AuthResult(created.id, auth.id, status, called, ast)


def authorize(order) -> tuple[str, str]:
    r = authorize_detailed(order)
    return r.paypal_order_id, r.authorization_id


# ---------------------------------------------------------------- capture / void

def _check_aid(aid) -> None:
    if not isinstance(aid, str) or not _ID_RE.fullmatch(aid):
        raise PayPalError("invalid_authorization_id")


def _existing_capture_id(aid):
    try:
        pa = _call(
            "get_authorization",
            lambda c: c.payments.get_authorized_payment({"authorization_id": aid}),
        ).body
        oid = pa.supplementary_data.related_ids.order_id
        o = _call("get_order", lambda c: c.orders.get_order({"id": oid})).body
        for pu in o.purchase_units or []:
            for cap in (pu.payments and pu.payments.captures) or []:
                if str(cap.status or "").upper() in ("COMPLETED", "PENDING") and cap.id:
                    return cap.id
    except (PayPalError, AttributeError, TypeError):
        return None
    return None


def capture(authorization_id: str, request_id: str | None = None) -> str:
    _check_aid(authorization_id)
    rid = request_id or f"{authorization_id}-capture"
    try:
        cap = _call(
            "capture",
            lambda c: c.payments.capture_authorized_payment(
                {
                    "authorization_id": authorization_id,
                    "paypal_request_id": rid,
                    "prefer": "return=representation",
                    "body": CaptureRequest(final_capture=True),
                }
            ),
        ).body
    except PayPalError as e:
        if e.code in ALREADY_CAPTURED:
            cid = _existing_capture_id(authorization_id)
            if cid:
                return cid
        raise
    st = str(getattr(cap, "status", "") or "").upper()
    if st in ("COMPLETED", "PENDING") and getattr(cap, "id", None):
        return cap.id
    raise PayPalError(_code(f"CAPTURE_{st or 'UNKNOWN'}"))


def void(authorization_id: str, request_id: str | None = None) -> None:
    _check_aid(authorization_id)
    rid = request_id or f"{authorization_id}-void"
    try:
        _call(
            "void",
            lambda c: c.payments.void_payment(
                {
                    "authorization_id": authorization_id,
                    "paypal_request_id": rid,
                    "prefer": "return=representation",
                }
            ),
        )
    except PayPalError as e:
        if e.code in ALREADY_VOIDED:
            return None
        raise
    return None


def refund(capture_id: str, amount: Decimal, currency: str, request_id: str) -> str:
    _check_aid(capture_id)
    if not isinstance(currency, str) or not _CUR_RE.fullmatch(currency):
        raise PayPalError("CURRENCY_MISMATCH")
    value = Decimal(str(amount)).quantize(CENT)
    if value <= 0:
        raise PayPalError("INVALID_AMOUNT")
    ref = _call(
        "refund",
        lambda c: c.payments.refund_captured_payment(
            {
                "capture_id": capture_id,
                "paypal_request_id": request_id,
                "prefer": "return=representation",
                "body": RefundRequest(amount=Money(currency_code=currency, value=f"{value:.2f}")),
            }
        ),
    ).body
    st = str(getattr(ref, "status", "") or "").upper()
    if st in ("COMPLETED", "PENDING") and getattr(ref, "id", None):
        return ref.id
    raise PayPalError(_code(f"REFUND_{st or 'UNKNOWN'}"))


def get_authorization_status(authorization_id: str) -> str:
    _check_aid(authorization_id)
    pa = _call(
        "get_authorization",
        lambda c: c.payments.get_authorized_payment({"authorization_id": authorization_id}),
    ).body
    return str(getattr(pa, "status", "") or "").upper()


# ---------------------------------------------------------------- vault

def create_setup_token(return_url: str, cancel_url: str, request_id: str) -> tuple[str, str]:
    body = SetupTokenRequest(
        payment_source=SetupTokenRequestPaymentSource(
            paypal=VaultPaypalWalletRequest(
                description="Sepilo agent purchases within your spending rules",
                usage_pattern=UsagePattern.IMMEDIATE,
                permit_multiple_payment_tokens=False,
                usage_type=PaypalPaymentTokenUsageType.MERCHANT,
                customer_type=PaypalPaymentTokenCustomerType.CONSUMER,
                experience_context=VaultExperienceContext(
                    brand_name="Sepilo",
                    locale="en-US",
                    shipping_preference=ExperienceContextShippingPreference.NO_SHIPPING,
                    return_url=return_url,
                    cancel_url=cancel_url,
                ),
            )
        )
    )
    r = _call(
        "setup_token",
        lambda c: c.vault.create_setup_token({"body": body, "paypal_request_id": request_id}),
    ).body
    href = next(
        (lk.href for lk in (getattr(r, "links", None) or []) if lk.rel == "approve" and lk.href),
        None,
    )
    if not getattr(r, "id", None) or not href:
        raise PayPalError("approve_link_missing")
    return r.id, href


def exchange_payment_token(setup_token_id: str) -> str:
    if not isinstance(setup_token_id, str) or not _ID_RE.fullmatch(setup_token_id):
        raise PayPalError("invalid_setup_token")
    body = PaymentTokenRequest(
        payment_source=PaymentTokenRequestPaymentSource(
            token=VaultTokenRequest(id=setup_token_id, mtype=VaultTokenRequestType.SETUP_TOKEN)
        )
    )
    r = _call(
        "payment_token",
        lambda c: c.vault.create_payment_token(
            {"body": body, "paypal_request_id": f"ptok-{setup_token_id}"}
        ),
    ).body
    if not getattr(r, "id", None):
        raise PayPalError("payment_token_missing")
    return r.id


# ---------------------------------------------------------------- buyer approval (no saved PayPal yet)

def _payer_wallet(return_url: str, cancel_url: str, save: bool):
    from paypalserversdk.models.paypal_experience_user_action import PaypalExperienceUserAction
    from paypalserversdk.models.paypal_wallet_attributes import PaypalWalletAttributes
    from paypalserversdk.models.paypal_wallet_experience_context import PaypalWalletExperienceContext
    from paypalserversdk.models.paypal_wallet_vault_instruction import PaypalWalletVaultInstruction
    from paypalserversdk.models.store_in_vault_instruction import StoreInVaultInstruction

    kw = {}
    if save:
        kw["attributes"] = PaypalWalletAttributes(vault=PaypalWalletVaultInstruction(
            store_in_vault=StoreInVaultInstruction.ON_SUCCESS,
            usage_type=PaypalPaymentTokenUsageType.MERCHANT,
            customer_type=PaypalPaymentTokenCustomerType.CONSUMER,
        ))
    return PaypalWallet(
        experience_context=PaypalWalletExperienceContext(
            brand_name="Sepilo",
            locale="en-US",
            shipping_preference=ExperienceContextShippingPreference.NO_SHIPPING,
            user_action=PaypalExperienceUserAction.PAY_NOW,
            return_url=return_url,
            cancel_url=cancel_url,
        ),
        **kw,
    )


def create_checkout(order, return_url: str, cancel_url: str) -> tuple[str, str]:
    """PayPal order the buyer approves once in PayPal. On approval PayPal also saves the account, so
    later agent purchases are paid without the buyer. Returns (paypal_order_id, approve_url)."""
    if not isinstance(getattr(order, "id", None), str) or not _ID_RE.fullmatch(order.id):
        raise PayPalError("INVALID_CART")
    body = build_order_request(order, VaultRef("paypal", "buyer-approval"))
    created = None
    for save, rid in ((True, f"{order.id}-pp"), (False, f"{order.id}-pp-nosave")):
        body.payment_source = PaymentSource(paypal=_payer_wallet(return_url, cancel_url, save))
        try:
            created = _call(
                "create_order_buyer",
                lambda c: c.orders.create_order(
                    {"body": body, "paypal_request_id": rid, "prefer": "return=representation"}
                ),
            ).body
            break
        except PayPalError as e:
            if not save or e.retryable:
                raise
            log.warning("paypal.save_on_purchase_refused code=%s; continuing without saving", e.code)
    href = next(
        (lk.href for lk in (getattr(created, "links", None) or [])
         if lk.rel in ("payer-action", "approve") and lk.href),
        None,
    )
    if not getattr(created, "id", None) or not href:
        raise PayPalError("approve_link_missing")
    return created.id, href


def _saved_wallet_id(o):
    try:
        v = o.payment_source.paypal.attributes.vault
    except AttributeError:
        return None
    vid = getattr(v, "id", None)
    st = str(getattr(v, "status", "") or "").upper()
    return vid if vid and st == "VAULTED" and _ID_RE.fullmatch(vid) else None


def authorize_approved(paypal_order_id: str, request_id: str) -> tuple[str, str | None]:
    """Authorize a PayPal order the buyer approved. Returns (authorization_id, saved_paypal_id or None)."""
    if not isinstance(paypal_order_id, str) or not _ID_RE.fullmatch(paypal_order_id):
        raise PayPalError("invalid_paypal_order_id")
    try:
        src = _call(
            "authorize_order",
            lambda c: c.orders.authorize_order(
                {"id": paypal_order_id, "paypal_request_id": request_id, "prefer": "return=representation"}
            ),
        ).body
    except PayPalError as e:
        if e.code != "ORDER_ALREADY_AUTHORIZED":
            raise
        src = _call("get_order", lambda c: c.orders.get_order({"id": paypal_order_id})).body
    auth = _first_auth(src)
    if auth is None:
        raise PayPalError("AUTHORIZATION_MISSING")
    ast = str(getattr(auth, "status", "") or "").upper()
    if ast != "CREATED":
        if ast == "PENDING":
            try:
                void(auth.id, request_id=f"{request_id}-void-pending")
            except PayPalError:
                pass
        raise PayPalError(_code(f"AUTHORIZATION_{ast or 'UNKNOWN'}"))
    return auth.id, _saved_wallet_id(src)
