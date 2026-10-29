"""Application settings loaded from environment variables.

Field names match the API-file entries in MANIFEST
(.claude/skills/setup-credentials/scripts/creds.py) exactly.

All secret fields are Optional at import time.
Use `settings.require("FIELD_NAME")` to get a non-None value;
it raises RuntimeError when the variable is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ------------------------------------------------------------------ #
    # PayPal
    # ------------------------------------------------------------------ #
    PAYPAL_ENV: str = "sandbox"
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_CLIENT_SECRET: Optional[str] = None
    PAYPAL_WEBHOOK_ID: Optional[str] = None
    PAYPAL_SANDBOX_BUYER_EMAIL: Optional[str] = None

    # ------------------------------------------------------------------ #
    # LLM — fast (Groq / OpenAI-compatible)
    # ------------------------------------------------------------------ #
    LLM_FAST_BASE_URL: Optional[str] = None
    LLM_FAST_API_KEY: Optional[str] = None
    LLM_FAST_MODEL: Optional[str] = None

    # Prompt-injection guard model (runs on the fast provider)
    LLM_GUARD_MODEL: Optional[str] = None

    # ------------------------------------------------------------------ #
    # LLM — smart (Jev / TypeSafe System One)
    # ------------------------------------------------------------------ #
    LLM_SMART_BASE_URL: Optional[str] = None
    LLM_SMART_API_KEY: Optional[str] = None
    LLM_SMART_MODEL: Optional[str] = None
    LLM_SMART_BUDGET_USD: Optional[float] = None
    LLM_SMART_RESERVE_USD: Optional[float] = None
    LLM_SMART_PRICE_IN_PER_MTOK: Optional[float] = None   # USD per 1M input tokens
    LLM_SMART_PRICE_OUT_PER_MTOK: Optional[float] = None  # USD per 1M output tokens

    # ------------------------------------------------------------------ #
    # Channel3 product catalog
    # ------------------------------------------------------------------ #
    CHANNEL3_API_KEY: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    DATABASE_URL: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Render deployment
    # ------------------------------------------------------------------ #
    RENDER_API_KEY: Optional[str] = None
    RENDER_WORKFLOW_SLUG: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Neo4j (graph store — future)
    # ------------------------------------------------------------------ #
    NEO4J_URI: Optional[str] = None
    NEO4J_USERNAME: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None

    # ------------------------------------------------------------------ #
    # IntentLock signing keys
    # ------------------------------------------------------------------ #
    INTENTLOCK_PROOF_PRIVATE_KEY: Optional[str] = None
    INTENTLOCK_PROOF_PUBLIC_KEY: Optional[str] = None
    INTENTLOCK_WALLET_PRIVATE_KEY: Optional[str] = None  # signs mandates + intents

    # ------------------------------------------------------------------ #
    # Web / public
    # ------------------------------------------------------------------ #
    WEB_ORIGIN: Optional[str] = None
    PUBLIC_BASE_URL: Optional[str] = None

    # ------------------------------------------------------------------ #
    # User auth: email one-time codes (Resend) + Google sign-in
    # ------------------------------------------------------------------ #
    AUTH_SECRET: Optional[str] = None  # HMAC key for sign-in codes
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM: Optional[str] = None
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None

    # Hosted shopping agent (apps/agent) that runs purchase requests for IntentLock-hosted agents
    AGENT_SERVICE_URL: Optional[str] = None
    AGENT_RUN_SECRET: Optional[str] = None

    # Operator key for the older open routes (/mandates, /orders, /lab …). Unset = those routes are closed.
    ADMIN_API_KEY: Optional[str] = None

    # Dispute managers: comma-separated emails. Signing in with one of these makes the user a dispute manager.
    DISPUTE_MANAGER_EMAILS: Optional[str] = None

    # Sepilo deal agent: open-web product search and page re-checks
    FIRECRAWL_API_KEY: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Runtime (not in MANIFEST)
    # ------------------------------------------------------------------ #
    PORT: int = 8000

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def require(self, name: str) -> str:
        """Return the value of a settings field, raising if not set."""
        value = getattr(self, name, None)
        if value is None:
            raise RuntimeError(
                f"Required environment variable '{name}' is not set. "
                "Add it to services/intentlock/.env or to the deployment environment."
            )
        return value  # type: ignore[return-value]


settings = Settings()


def web_origins() -> list[str]:
    """WEB_ORIGIN as a list: comma-separated, trailing slashes dropped, https:// added when missing.
    The first entry is the canonical web URL (redirects, Google sign-in)."""
    out: list[str] = []
    for raw in (settings.WEB_ORIGIN or "").split(","):
        o = raw.strip().rstrip("/")
        if not o or o == "__FILL_ME__":
            continue
        if "://" not in o:
            o = f"https://{o}"
        if o not in out:
            out.append(o)
    return out or ["http://localhost:3000"]
