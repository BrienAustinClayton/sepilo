"""IntentLock FastAPI application entry point."""

from __future__ import annotations

import asyncio
import os
import subprocess
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.access import require_admin
from app.config import settings, web_origins
from app.errors import http_exception_handler, unhandled_exception_handler
from app.api import (
    agents,
    auth,
    approvals,
    catalog,
    chats,
    checkout,
    console,
    disputes,
    graph,
    intents,
    lab,
    llm,
    mandates,
    me,
    orders,
    paypal_return,
    proofs,
    schedule,
    users,
    vault,
    webhooks,
)


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        sha = result.stdout.strip()
        return sha if sha else "dev"
    except Exception:
        return "dev"


VERSION = _git_sha()


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    from app.hosted_agents import run_loop as agent_run_watchdog
    from app.jobs.expire_approvals import run_loop
    tasks = [asyncio.create_task(run_loop(interval_s=60)), asyncio.create_task(agent_run_watchdog(interval_s=20))]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


_DOCS = os.environ.get("API_DOCS") == "1"  # API schema stays private unless turned on (local dev)

app = FastAPI(
    title="Sepilo API",
    description="Autonomous agent payment guard service",
    version="0.1.0",
    lifespan=_lifespan,
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)

# ------------------------------------------------------------------ #
# CORS — default to localhost:3000 if WEB_ORIGIN is not configured
# ------------------------------------------------------------------ #
_web_origins = web_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_web_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ #
# Error handlers — cover both Starlette and FastAPI HTTP exceptions
# so 404/405 also return {"error","reason"} JSON.
# ------------------------------------------------------------------ #
app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(FastAPIHTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # str(exc) includes source file paths and echoes input; send field + message only.
    parts = []
    for err in exc.errors()[:3]:
        field = ".".join(str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path"))
        parts.append(f"{field}: {err.get('msg', 'invalid')}" if field else str(err.get("msg", "invalid")))
    return JSONResponse(
        status_code=422,
        content={"error": "unprocessable", "reason": "; ".join(parts) or "Invalid request."},
    )


# ------------------------------------------------------------------ #
# Health
# ------------------------------------------------------------------ #
@app.get("/health", tags=["health"])
async def health() -> dict[str, Any]:
    return {"ok": True, "version": VERSION}


@app.api_route("/ping", methods=["GET", "HEAD"], tags=["health"], include_in_schema=False)
async def ping() -> dict[str, bool]:
    """For uptime / keep-awake cron jobs: always 200, no database, no external calls."""
    return {"ok": True}


# ------------------------------------------------------------------ #
# Routers
# ------------------------------------------------------------------ #
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(disputes.me_router)
app.include_router(disputes.router)
app.include_router(chats.router)
app.include_router(users.router, dependencies=[Depends(require_admin)])
app.include_router(vault.router)
app.include_router(paypal_return.router)
app.include_router(agents.router)
app.include_router(mandates.router, dependencies=[Depends(require_admin)])
app.include_router(intents.router)
app.include_router(catalog.router)
app.include_router(checkout.router)
# proofs before orders: proofs owns GET /orders/{order_id}/proof (orders.py keeps a stub of it)
app.include_router(proofs.router)
app.include_router(orders.router, dependencies=[Depends(require_admin)])
app.include_router(approvals.router, dependencies=[Depends(require_admin)])
app.include_router(graph.router, dependencies=[Depends(require_admin)])
app.include_router(schedule.router)
app.include_router(lab.router)
app.include_router(lab.me_router)
app.include_router(webhooks.router)
app.include_router(llm.router, dependencies=[Depends(require_admin)])
app.include_router(console.router, dependencies=[Depends(require_admin)])
