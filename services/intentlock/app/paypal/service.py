"""PayPal service interface. Mock is the default.

Sandbox lives in app/paypal/sandbox.py (P1-T09). Never import the PayPal SDK here.
"""
import hashlib
import os
import threading
from decimal import Decimal


class PayPalError(Exception):
    def __init__(self, code: str, debug_id: str | None = None, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.debug_id = debug_id
        self.retryable = retryable


def paypal_mode() -> str:
    v = os.environ.get("PAYPAL_MODE", "mock").strip().lower()
    return v if v in ("mock", "sandbox") else "invalid"


_LOCK = threading.Lock()
_CALLS: list[dict] = []
_AUTH: dict[str, str] = {}
_CAPTURE_IDS: dict[str, str] = {}
_REFUNDS: dict[str, str] = {}
_FAIL: dict[str, list[PayPalError]] = {}
_SETUP: dict[str, str] = {}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest().upper()[:16]


def _take_failure(op: str) -> PayPalError | None:
    with _LOCK:
        q = _FAIL.get(op)
        if q:
            return q.pop(0)
    return None


def _record(call: dict) -> None:
    with _LOCK:
        _CALLS.append(call)


def _mock_authorize(order) -> tuple[str, str]:
    total = Decimal(str(order.total))
    _record({
        "op": "authorize", "order_id": order.id, "request_id": order.id,
        "amount": f"{total:.2f}", "currency": order.currency,
        "items": len(order.cart_json or []),
    })
    err = _take_failure("authorize")
    if err is not None:
        raise err
    if total <= 0:
        raise PayPalError("INVALID_AMOUNT")
    oid = "MOCK-O-" + _h(order.id)
    aid = "MOCK-A-" + _h(order.id)
    with _LOCK:
        _AUTH.setdefault(aid, "authorized")
    return oid, aid


def _mock_capture(aid: str, request_id: str | None) -> str:
    _record({"op": "capture", "authorization_id": aid, "request_id": request_id})
    err = _take_failure("capture")
    if err is not None:
        raise err
    with _LOCK:
        # Mock state is in-memory; a MOCK-A-* id from before a process restart is treated as still authorized.
        state = _AUTH.get(aid) or ("authorized" if str(aid).startswith("MOCK-A-") else None)
        if state is None:
            raise PayPalError("AUTHORIZATION_NOT_FOUND")
        if state == "voided":
            raise PayPalError("AUTHORIZATION_VOIDED")
        if state == "authorized":
            _AUTH[aid] = "captured"
            _CAPTURE_IDS[aid] = "MOCK-C-" + _h(aid)
        return _CAPTURE_IDS[aid]


def _mock_void(aid: str, request_id: str | None) -> None:
    _record({"op": "void", "authorization_id": aid, "request_id": request_id})
    err = _take_failure("void")
    if err is not None:
        raise err
    with _LOCK:
        # Mock state is in-memory; a MOCK-A-* id from before a process restart is treated as still authorized.
        state = _AUTH.get(aid) or ("authorized" if str(aid).startswith("MOCK-A-") else None)
        if state is None:
            raise PayPalError("AUTHORIZATION_NOT_FOUND")
        if state == "captured":
            raise PayPalError("AUTHORIZATION_ALREADY_CAPTURED")
        _AUTH[aid] = "voided"


def _mock_refund(capture_id: str, amount: Decimal, currency: str, request_id: str) -> str:
    _record({"op": "refund", "capture_id": capture_id, "amount": f"{Decimal(str(amount)):.2f}",
             "currency": currency, "request_id": request_id})
    err = _take_failure("refund")
    if err is not None:
        raise err
    if Decimal(str(amount)) <= 0:
        raise PayPalError("INVALID_AMOUNT")
    if not str(capture_id).startswith("MOCK-C-"):
        raise PayPalError("CAPTURE_NOT_FOUND")
    with _LOCK:
        return _REFUNDS.setdefault(request_id, "MOCK-R-" + _h(request_id))


def _impl():
    mode = paypal_mode()
    if mode == "mock":
        return None
    if mode == "sandbox":
        try:
            from app.paypal import sandbox
        except ImportError:
            raise PayPalError("sandbox_not_implemented") from None
        return sandbox
    raise PayPalError("invalid_mode")


def authorize(order) -> tuple[str, str]:
    impl = _impl()
    return _mock_authorize(order) if impl is None else impl.authorize(order)


def capture(authorization_id: str, request_id: str | None = None) -> str:
    impl = _impl()
    if impl is None:
        return _mock_capture(authorization_id, request_id)
    return impl.capture(authorization_id, request_id=request_id)


def refund(capture_id: str, amount: Decimal, currency: str, request_id: str) -> str:
    impl = _impl()
    if impl is None:
        return _mock_refund(capture_id, amount, currency, request_id)
    return impl.refund(capture_id, amount, currency, request_id)


def void(authorization_id: str, request_id: str | None = None) -> None:
    impl = _impl()
    if impl is None:
        return _mock_void(authorization_id, request_id)
    return impl.void(authorization_id, request_id=request_id)


def _mock_create_checkout(order, return_url: str) -> tuple[str, str]:
    _record({"op": "create_checkout", "order_id": order.id})
    err = _take_failure("create_checkout")
    if err is not None:
        raise err
    oid = "MOCK-O-" + _h(order.id)
    sep = "&" if "?" in return_url else "?"
    return oid, f"{return_url}{sep}token={oid}"


def _mock_authorize_approved(paypal_order_id: str) -> tuple[str, str | None]:
    _record({"op": "authorize_approved", "paypal_order_id": paypal_order_id})
    err = _take_failure("authorize_approved")
    if err is not None:
        raise err
    aid = "MOCK-A-" + _h(paypal_order_id)
    with _LOCK:
        _AUTH.setdefault(aid, "authorized")
    return aid, "MOCK-PT-" + _h(paypal_order_id)


def create_checkout(order, return_url: str, cancel_url: str) -> tuple[str, str]:
    """A PayPal order the buyer approves in PayPal (used when no PayPal account is saved yet)."""
    impl = _impl()
    if impl is None:
        return _mock_create_checkout(order, return_url)
    return impl.create_checkout(order, return_url, cancel_url)


def authorize_approved(paypal_order_id: str, request_id: str) -> tuple[str, str | None]:
    """Authorize a buyer-approved PayPal order. Returns (authorization_id, saved PayPal id or None)."""
    impl = _impl()
    if impl is None:
        return _mock_authorize_approved(paypal_order_id)
    return impl.authorize_approved(paypal_order_id, request_id)


def has_saved_payment(token: str | None) -> bool:
    """Whether agent purchases can be paid without the buyer (a saved PayPal account usable in this mode)."""
    if not token:
        return False
    if paypal_mode() != "sandbox":
        return True
    from app.paypal.sandbox import parse_vault_ref
    return parse_vault_ref(token) is not None


def _mock_setup_token(return_url: str, request_id: str) -> tuple[str, str]:
    _record({"op": "setup_token", "request_id": request_id})
    err = _take_failure("setup_token")
    if err is not None:
        raise err
    sid = "MOCK-ST-" + _h(request_id)
    with _LOCK:
        _SETUP[sid] = request_id
    sep = "&" if "?" in return_url else "?"
    return sid, f"{return_url}{sep}approval_token_id={sid}"


def _mock_exchange(setup_token_id: str) -> str:
    _record({"op": "payment_token", "setup_token_id": setup_token_id})
    err = _take_failure("payment_token")
    if err is not None:
        raise err
    if not str(setup_token_id).startswith("MOCK-ST-"):
        raise PayPalError("SETUP_TOKEN_NOT_FOUND")
    return "MOCK-PT-" + _h(setup_token_id)


def create_setup_token(return_url: str, cancel_url: str, request_id: str) -> tuple[str, str]:
    impl = _impl()
    if impl is None:
        return _mock_setup_token(return_url, request_id)
    return impl.create_setup_token(return_url, cancel_url, request_id)


def exchange_payment_token(setup_token_id: str) -> str:
    impl = _impl()
    return _mock_exchange(setup_token_id) if impl is None else impl.exchange_payment_token(setup_token_id)


def reset_mock() -> None:
    with _LOCK:
        _CALLS.clear()
        _AUTH.clear()
        _CAPTURE_IDS.clear()
        _REFUNDS.clear()
        _FAIL.clear()
        _SETUP.clear()


def mock_calls() -> list[dict]:
    with _LOCK:
        return [dict(c) for c in _CALLS]


def mock_fail_next(op: str, error: PayPalError, times: int = 1) -> None:
    with _LOCK:
        _FAIL.setdefault(op, []).extend([error] * times)
