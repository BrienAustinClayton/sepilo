"""Signed-in user's shipping address. Orders only ship here; changing it needs a fresh sign-in."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import untrusted, velocity
from app.auth import current_session, current_user, send_security_notice
from app.db import get_db
from app.models import User, UserSession
from app.signing import iso_z

router = APIRouter(prefix="/me", tags=["address"])


class AddressIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    line1: str = Field(min_length=1, max_length=200)
    line2: Optional[str] = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: Optional[str] = Field(default=None, max_length=100)
    postal_code: str = Field(pattern=r"^[A-Za-z0-9 -]{2,20}$")
    country: str = Field(pattern=r"^[A-Za-z]{2}$")
    phone: Optional[str] = Field(default=None, pattern=r"^\+?[0-9 ()-]{6,20}$")


def _address_out(user: User) -> dict[str, Any]:
    return {
        "address": user.shipping_address or None,
        "updated_at": iso_z(user.address_updated_at) if user.address_updated_at else None,
    }


@router.get("/address")
def get_address(user: User = Depends(current_user)) -> dict[str, Any]:
    return _address_out(user)


@router.put("/address")
def put_address(body: AddressIn, user: User = Depends(current_user), sess: UserSession = Depends(current_session),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    velocity.require_fresh_sign_in(sess)
    fields = {
        "name": untrusted.clean(body.name, 100),
        "line1": untrusted.clean(body.line1, 200),
        "line2": untrusted.clean(body.line2, 200) if body.line2 else None,
        "city": untrusted.clean(body.city, 100),
        "region": untrusted.clean(body.region, 100) if body.region else None,
        "postal_code": untrusted.clean(body.postal_code, 20),
        "country": body.country.upper(),
        "phone": untrusted.clean(body.phone, 20) if body.phone else None,
    }
    user.shipping_address = {k: v for k, v in fields.items() if v is not None}
    user.address_updated_at = datetime.now(timezone.utc)
    db.commit()
    send_security_notice(user.email, "Your Sepilo shipping address changed",
                         f"Orders will now ship to {fields['city']}, {fields['country']}.")
    return _address_out(user)
