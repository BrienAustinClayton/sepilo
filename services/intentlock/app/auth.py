"""User authentication: email one-time codes (Resend), Google sign-in, bearer sessions.

Only hashes are stored: HMAC-SHA256(AUTH_SECRET, email:code) for codes and SHA-256 of
session tokens. The web app keeps the raw session token in an httpOnly cookie on its own
origin and sends it here as a bearer token.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings, web_origins
from app.db import get_db
from app.ids import new_id
from app.models import AuthCode, User, UserSession

log = logging.getLogger("intentlock.auth")

CODE_TTL = timedelta(minutes=10)
CODE_MAX_ATTEMPTS = 5
CODE_COOLDOWN = timedelta(seconds=30)
CODE_WINDOW = timedelta(minutes=15)
CODE_WINDOW_MAX = 5
SESSION_TTL = timedelta(days=30)

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
PKCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

RESEND_URL = "https://api.resend.com/emails"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def http(self) -> HTTPException:
        return HTTPException(status_code=self.status, detail={"error": self.code, "reason": self.message})


def _cfg(name: str) -> str | None:
    v = getattr(settings, name, None)
    return None if v in (None, "", "__FILL_ME__") else v


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def web_origin() -> str:
    return web_origins()[0]


def _is_local() -> bool:
    return web_origin().startswith(("http://localhost", "http://127.0.0.1"))


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AuthError(422, "invalid_email", "Enter a valid email address.")
    return email


def _code_hash(email: str, code: str) -> str:
    secret = _cfg("AUTH_SECRET")
    if not secret:
        raise AuthError(503, "auth_not_configured", "Sign-in is not configured (AUTH_SECRET).")
    return hmac.new(secret.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


# --------------------------------------------------------------------------- #
# Users and sessions
# --------------------------------------------------------------------------- #

def next_step(user: User) -> str:
    if user.signup_completed_at is None:
        return "signup"
    if user.onboarded_at is None:
        return "onboarding"
    return "app"


def dispute_manager_emails() -> set[str]:
    raw = _cfg("DISPUTE_MANAGER_EMAILS") or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_dispute_manager(user: User) -> bool:
    return bool(user.email and user.email_verified_at is not None and user.email.strip().lower() in dispute_manager_emails())


def user_dto(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "country": user.country,
        "currency": user.currency,
        "company": user.company,
        "onboarding": user.onboarding,
        "has_address": bool(user.shipping_address),
        "next": next_step(user),
        "role": "dispute_manager" if is_dispute_manager(user) else "user",
    }


def _login(db: Session, user: User, user_agent: str | None, is_new: bool) -> dict[str, Any]:
    t = utcnow()
    user.last_login_at = t
    db.flush()
    token = secrets.token_urlsafe(32)
    sess = UserSession(
        id=new_id("ses"), user_id=user.id, token_hash=_token_hash(token),
        user_agent=(user_agent or "")[:300] or None, expires_at=t + SESSION_TTL, created_at=t,
    )
    db.add(sess)
    db.commit()
    return {"token": token, "expires_at": _iso(sess.expires_at), "is_new": is_new,
            "next": next_step(user), "user": user_dto(user)}


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    sess = None
    if token:
        sess = db.execute(
            select(UserSession).where(UserSession.token_hash == _token_hash(token))
        ).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or sess.expires_at <= utcnow():
        raise HTTPException(status_code=401, detail={"error": "unauthenticated", "reason": "Sign in required."})
    return sess


def current_user(sess: UserSession = Depends(current_session), db: Session = Depends(get_db)) -> User:
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "unauthenticated", "reason": "Sign in required."})
    return user


def require_dispute_manager(user: User = Depends(current_user)) -> User:
    if not is_dispute_manager(user):
        raise HTTPException(status_code=403, detail={"error": "forbidden", "reason": "Dispute managers only."})
    return user


def logout(db: Session, sess: UserSession) -> None:
    sess.revoked_at = utcnow()
    db.commit()


# --------------------------------------------------------------------------- #
# Email one-time codes
# --------------------------------------------------------------------------- #

def _email_bodies(code: str) -> tuple[str, str]:
    text = (
        f"Your Sepilo sign-in code is {code}\n\n"
        "It expires in 10 minutes. If you didn't try to sign in, you can ignore this email."
    )
    html = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:420px;margin:0 auto;padding:32px 24px;color:#111318">
<p style="font-size:15px;font-weight:600;margin:0 0 24px">Sepilo</p>
<p style="font-size:14px;margin:0 0 12px">Your sign-in code:</p>
<p style="font-size:32px;letter-spacing:8px;font-weight:700;font-family:ui-monospace,Menlo,monospace;margin:0 0 24px">{code}</p>
<p style="font-size:13px;color:#565d6b;margin:0">It expires in 10 minutes. If you didn't try to sign in, you can ignore this email.</p>
</div>"""
    return text, html


def send_code_email(email: str, code: str) -> None:
    key = _cfg("RESEND_API_KEY")
    if not key:
        if _is_local():
            log.warning("auth.dev_code email=%s code=%s (RESEND_API_KEY unset; local dev only)", email, code)
            return
        raise AuthError(503, "email_not_configured", "Email sign-in is not configured.")
    text, html = _email_bodies(code)
    body = {
        "from": _cfg("RESEND_FROM") or "Sepilo <support@sepilo.space>",
        "to": [email],
        "subject": f"{code} is your Sepilo sign-in code",
        "text": text,
        "html": html,
    }
    try:
        r = httpx.post(RESEND_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=10)
    except httpx.HTTPError:
        raise AuthError(502, "email_send_failed", "Could not send the email. Try again.")
    if r.status_code >= 300:
        log.warning("auth.resend_failed status=%s body=%s", r.status_code, r.text[:300])
        raise AuthError(502, "email_send_failed", "Could not send the email. Try again.")


def start_email_code(db: Session, raw_email: str) -> None:
    email = normalize_email(raw_email)
    t = utcnow()
    recent = db.execute(
        select(AuthCode)
        .where(AuthCode.email == email, AuthCode.created_at > t - CODE_WINDOW)
        .order_by(AuthCode.created_at.desc())
    ).scalars().all()
    if recent and recent[0].created_at > t - CODE_COOLDOWN:
        raise AuthError(429, "slow_down", "Wait a few seconds before requesting another code.")
    if len(recent) >= CODE_WINDOW_MAX:
        raise AuthError(429, "too_many_codes", "Too many codes requested. Try again in 15 minutes.")
    for r in recent:
        if r.consumed_at is None:
            r.consumed_at = t
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(AuthCode(id=new_id("otp"), email=email, code_hash=_code_hash(email, code),
                    attempts=0, expires_at=t + CODE_TTL, created_at=t))
    db.flush()
    try:
        send_code_email(email, code)
    except AuthError:
        db.rollback()
        raise
    db.commit()


def verify_email_code(db: Session, raw_email: str, raw_code: str, user_agent: str | None) -> dict[str, Any]:
    email = normalize_email(raw_email)
    code = (raw_code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise AuthError(400, "invalid_code", "That code is not right.")
    t = utcnow()
    row = db.execute(
        select(AuthCode)
        .where(AuthCode.email == email, AuthCode.consumed_at.is_(None))
        .order_by(AuthCode.created_at.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.expires_at <= t:
        raise AuthError(400, "code_expired", "This code has expired. Request a new one.")
    if not hmac.compare_digest(row.code_hash, _code_hash(email, code)):
        row.attempts += 1
        if row.attempts >= CODE_MAX_ATTEMPTS:
            row.consumed_at = t
            db.commit()
            raise AuthError(400, "too_many_attempts", "Too many wrong attempts. Request a new code.")
        db.commit()
        raise AuthError(400, "invalid_code", "That code is not right.")
    row.consumed_at = t

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    is_new = user is None
    if is_new:
        user = User(id=new_id("usr"), name=email.split("@")[0], email=email)
        db.add(user)
    if user.email_verified_at is None:
        user.email_verified_at = t
    return _login(db, user, user_agent, is_new)


# --------------------------------------------------------------------------- #
# Google sign-in (authorization code + PKCE; the web app holds state/verifier)
# --------------------------------------------------------------------------- #

def google_redirect_uri() -> str:
    return f"{web_origin()}/api/auth/google/callback"


def _google_creds() -> tuple[str, str]:
    cid, secret = _cfg("GOOGLE_CLIENT_ID"), _cfg("GOOGLE_CLIENT_SECRET")
    if not cid or not secret:
        raise AuthError(503, "google_not_configured", "Google sign-in is not configured.")
    return cid, secret


def google_auth_url(state: str, code_challenge: str) -> str:
    cid, _ = _google_creds()
    if not PKCE_RE.match(state or "") or not PKCE_RE.match(code_challenge or ""):
        raise AuthError(422, "invalid_request", "Invalid sign-in request.")
    return GOOGLE_AUTH_URL + "?" + urlencode({
        "client_id": cid,
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })


def _id_token_claims(id_token: Any) -> dict[str, Any]:
    # The token comes straight from Google's token endpoint over TLS, so per OIDC Core
    # 3.1.3.7 the TLS server check stands in for signature verification.
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        assert isinstance(claims, dict)
        return claims
    except Exception:
        raise AuthError(400, "google_exchange_failed", "Google sign-in failed. Try again.")


def google_login(db: Session, code: str, code_verifier: str, user_agent: str | None) -> dict[str, Any]:
    cid, secret = _google_creds()
    if not code or len(code) > 2048 or not PKCE_RE.match(code_verifier or ""):
        raise AuthError(422, "invalid_request", "Invalid sign-in request.")
    try:
        r = httpx.post(GOOGLE_TOKEN_URL, timeout=10, data={
            "code": code,
            "client_id": cid,
            "client_secret": secret,
            "redirect_uri": google_redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        })
    except httpx.HTTPError:
        raise AuthError(502, "google_unreachable", "Could not reach Google. Try again.")
    if r.status_code != 200:
        log.warning("auth.google_exchange_failed status=%s body=%s", r.status_code, r.text[:300])
        raise AuthError(400, "google_exchange_failed", "Google sign-in failed. Try again.")
    claims = _id_token_claims(r.json().get("id_token"))
    if (claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != cid
            or not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= utcnow().timestamp()
            or claims.get("email_verified") is not True or not claims.get("sub")):
        raise AuthError(400, "google_exchange_failed", "Google sign-in failed. Try again.")
    sub = str(claims["sub"])
    email = normalize_email(str(claims.get("email", "")))

    user = db.execute(select(User).where(User.google_sub == sub)).scalar_one_or_none()
    if user is None:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is not None and user.google_sub not in (None, sub):
            raise AuthError(409, "account_conflict", "This email is linked to a different Google account.")
    is_new = user is None
    if is_new:
        user = User(id=new_id("usr"), name=str(claims.get("name") or email.split("@")[0])[:80], email=email)
        db.add(user)
    user.google_sub = sub
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    if not user.avatar_url and isinstance(claims.get("picture"), str):
        user.avatar_url = claims["picture"][:500]
    return _login(db, user, user_agent, is_new)


def send_security_notice(email: str | None, subject: str, text: str) -> None:
    """Best-effort email when something sensitive changes on the account (payment method, new agent).
    Never raises: a failed notice must not undo the change; it is logged for developers instead."""
    key = _cfg("RESEND_API_KEY")
    if not email or not key:
        log.info("auth.security_notice_skipped subject=%r", subject)
        return
    body = {"from": _cfg("RESEND_FROM") or "Sepilo <support@sepilo.space>", "to": [email], "subject": subject,
            "text": text + "\n\nIf this wasn't you, sign in to Sepilo now and disconnect it."}
    try:
        r = httpx.post(RESEND_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=10)
        if r.status_code >= 300:
            log.warning("auth.security_notice_failed status=%s", r.status_code)
    except httpx.HTTPError as e:
        log.warning("auth.security_notice_failed %s", type(e).__name__)
