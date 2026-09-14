"""Public, real-call web application for the limited Later, Me. hackathon trial.

The browser never receives CALL-E or OpenAI credentials.  It can only create,
change, cancel and inspect its own reservation through an HttpOnly session
cookie.  Real dispatch happens separately in ``public_dispatch_due.py``.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import public_db

COOKIE_NAME = "later_me_session"
MINIMUM_LEAD = timedelta(hours=4)
MAX_MESSAGE_CHARS = 500


class ProfileInput(BaseModel):
    language: str
    phone: str
    own_number_confirmed: bool
    future_calls_authorized: bool


class ReservationInput(BaseModel):
    scheduled_for: str
    future_message: str | None = None
    timezone: str | None = None


class ChangeReservationInput(BaseModel):
    scheduled_for: str
    future_message: str | None = None
    timezone: str | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_env_datetime(name: str) -> datetime | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an ISO-8601 datetime with timezone.") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{name} must include a timezone offset.")
    return parsed.astimezone(timezone.utc)


def _ten_year_limit(now: datetime) -> datetime:
    try:
        return now.replace(year=now.year + 10)
    except ValueError:
        return now.replace(year=now.year + 10, day=28)


def parse_browser_schedule(value: str, timezone_name: str | None) -> datetime:
    """Interpret the browser's local ``YYYY-MM-DD HH:MM`` safely.

    Existing localhost builds continue to send the same string.  The public
    build adds an IANA timezone name so Render can convert the visitor's local
    choice to an absolute instant instead of accidentally treating it as UTC.
    """
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Check the reservation date and time.") from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError as exc:
        raise ValueError("The browser timezone could not be recognized.") from exc
    return parsed.replace(tzinfo=zone).astimezone(timezone.utc)


def validate_public_schedule(target: datetime, now: datetime | None = None) -> datetime:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    target = target.astimezone(timezone.utc)
    if target < current + MINIMUM_LEAD:
        raise ValueError("Calls must be scheduled at least 4 hours in the future.")
    maximum = _ten_year_limit(current)
    dispatch_end = _parse_env_datetime("PUBLIC_DISPATCH_END_AT")
    if dispatch_end is not None:
        maximum = min(maximum, dispatch_end)
    if target > maximum:
        if dispatch_end is not None and maximum == dispatch_end:
            raise ValueError(
                "This limited hackathon trial only accepts calls scheduled before its public dispatch end time."
            )
        raise ValueError("Calls can be scheduled up to 10 years in the future.")
    return target


def trial_window() -> dict[str, Any]:
    booking_close = _parse_env_datetime("PUBLIC_BOOKING_CLOSE_AT")
    dispatch_end = _parse_env_datetime("PUBLIC_DISPATCH_END_AT")
    now = datetime.now(timezone.utc)
    enabled = _env_bool("PUBLIC_LIVE_ENABLED", True)
    accepting = enabled and (booking_close is None or now < booking_close)
    snapshot = public_db.budget_snapshot()
    if snapshot["slots_remaining"] <= 0:
        accepting = False
    return {
        **snapshot,
        "enabled": enabled,
        "accepting_reservations": accepting,
        "booking_close_at": booking_close.isoformat() if booking_close else None,
        "dispatch_end_at": dispatch_end.isoformat() if dispatch_end else None,
        "real_calls": True,
    }


def assert_trial_accepting() -> None:
    info = trial_window()
    if not info["enabled"]:
        raise HTTPException(status_code=409, detail="The limited public trial is currently closed.")
    if not info["accepting_reservations"]:
        if info["slots_remaining"] <= 0:
            raise HTTPException(
                status_code=409,
                detail="The limited public trial has reached its available real-call capacity.",
            )
        raise HTTPException(status_code=409, detail="The limited public booking window has closed.")


def _error(exc: public_db.PublicStoreError) -> HTTPException:
    status = 400
    if isinstance(
        exc,
        (
            public_db.CapacityReachedError,
            public_db.PendingExistsError,
            public_db.NoPendingError,
            public_db.ProfileExistsError,
            public_db.PhoneAlreadyUsedError,
            public_db.TrialAlreadyUsedError,
        ),
    ):
        status = 409
    return HTTPException(status_code=status, detail=str(exc), headers={"X-Later-Me-Code": exc.code})


def _session(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(COOKIE_NAME)
    created = False
    if not token:
        token = public_db.new_session_token()
        created = True
    row = public_db.ensure_session(token)
    if created:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=60 * 60 * 24 * 45,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
    return row


@asynccontextmanager
async def lifespan(_: FastAPI):
    public_db.init_schema()
    yield


app = FastAPI(title="Later, Me. Public Live Trial", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "mode": "public-live"}


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    info = trial_window()
    return {
        "ok": True,
        "dispatch_enabled": True,
        "delivery_mode": "public-live",
        "task_scheduler_mutation_enabled": False,
        "storage_mode": "postgres",
        "instance_id": None,
        "booking_minimum_minutes": 240,
        "dev_short_horizon_enabled": False,
        "public_dispatch_end_at": info["dispatch_end_at"],
        "slots_remaining": info["slots_remaining"],
    }


@app.get("/api/profile")
def get_profile(request: Request, response: Response) -> dict[str, Any]:
    session = _session(request, response)
    return public_db.profile_status(session["id"])


@app.post("/api/profile")
def create_profile(payload: ProfileInput, request: Request, response: Response) -> dict[str, Any]:
    assert_trial_accepting()
    session = _session(request, response)
    try:
        return public_db.save_profile(
            session["id"],
            language=payload.language,
            phone=payload.phone,
            own_number_confirmed=payload.own_number_confirmed,
            future_calls_authorized=payload.future_calls_authorized,
        )
    except public_db.PublicStoreError as exc:
        raise _error(exc) from exc


@app.get("/api/state")
def get_state(request: Request, response: Response) -> dict[str, Any]:
    session = _session(request, response)
    state = public_db.state_for_session(session["id"])
    state["trial"] = trial_window()
    return state


@app.post("/api/calls")
def create_call(payload: ReservationInput, request: Request, response: Response) -> dict[str, Any]:
    assert_trial_accepting()
    session = _session(request, response)
    try:
        scheduled = validate_public_schedule(
            parse_browser_schedule(payload.scheduled_for, payload.timezone)
        )
        pending = public_db.create_reservation(
            session["id"],
            scheduled_for=scheduled,
            future_message=(payload.future_message or "")[:MAX_MESSAGE_CHARS],
        )
        return {"pending": pending, "trial": trial_window()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except public_db.PublicStoreError as exc:
        raise _error(exc) from exc


@app.post("/api/calls/change")
def change_call(payload: ChangeReservationInput, request: Request, response: Response) -> dict[str, Any]:
    session = _session(request, response)
    try:
        scheduled = validate_public_schedule(
            parse_browser_schedule(payload.scheduled_for, payload.timezone)
        )
        pending = public_db.change_reservation(session["id"], scheduled_for=scheduled)
        return {"pending": pending, "trial": trial_window()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except public_db.PublicStoreError as exc:
        raise _error(exc) from exc


@app.delete("/api/calls")
def cancel_call(request: Request, response: Response) -> dict[str, Any]:
    session = _session(request, response)
    try:
        public_db.cancel_reservation(session["id"])
    except public_db.PublicStoreError as exc:
        raise _error(exc) from exc
    return {"pending": None, "trial": trial_window()}


WEB_DIST = Path(os.environ.get("WEB_DIST_DIR", "web/dist")).resolve()
if WEB_DIST.is_dir():
    # API routes are registered first, so this final mount only handles the React app/assets.
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
