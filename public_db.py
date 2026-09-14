"""Postgres storage for the limited public Later, Me. hackathon trial.

This module is intentionally separate from the Windows/local storage path.  It
stores only public-trial state, isolates each visitor by an opaque cookie token,
and reserves a finite CALL-E slot at booking time so the trial cannot accept
more real calls than the configured budget allows.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from cryptography.fernet import Fernet
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
PHONE_FORMATTING = re.compile(r"[\s().-]+")
ACTIVE_STATUSES = ("pending", "dispatching")
TERMINAL_STATUSES = ("completed", "failed", "canceled")


class PublicStoreError(RuntimeError):
    code = "PUBLIC_STORE_ERROR"


class ValidationError(PublicStoreError):
    code = "VALIDATION_FAILED"


class CapacityReachedError(PublicStoreError):
    code = "CAPACITY_REACHED"


class PendingExistsError(PublicStoreError):
    code = "PENDING_CALL_EXISTS"


class NoPendingError(PublicStoreError):
    code = "NO_PENDING_CALL"


class ProfileExistsError(PublicStoreError):
    code = "PROFILE_ALREADY_EXISTS"


class PhoneAlreadyUsedError(PublicStoreError):
    code = "PHONE_ALREADY_USED"


class TrialAlreadyUsedError(PublicStoreError):
    code = "PUBLIC_TRIAL_ALREADY_USED"


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required.")
    return value


def connect():
    return psycopg.connect(_database_url(), row_factory=dict_row)


def normalize_phone(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("A phone number is required.")
    normalized = PHONE_FORMATTING.sub("", value.strip())
    if not PHONE_PATTERN.fullmatch(normalized):
        raise ValidationError(
            "Use an international phone number beginning with + and country code."
        )
    return normalized


def _secret_material() -> bytes:
    value = os.environ.get("PHONE_ENCRYPTION_KEY", "").strip()
    if not value:
        raise RuntimeError("PHONE_ENCRYPTION_KEY is required.")
    return value.encode("utf-8")


def _fernet() -> Fernet:
    derived = hashlib.sha256(_secret_material()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_phone(phone: str) -> str:
    return _fernet().encrypt(phone.encode("utf-8")).decode("ascii")


def decrypt_phone(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def phone_fingerprint(phone: str) -> str:
    key = hashlib.sha256(b"later-me-phone-hash\0" + _secret_material()).digest()
    return hmac.new(key, phone.encode("utf-8"), hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def configured_max_calls() -> int | None:
    raw = os.environ.get("CALL_E_MAX_CALLS")
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("CALL_E_MAX_CALLS must be an integer.") from exc
    if value < 1:
        raise RuntimeError("CALL_E_MAX_CALLS must be at least 1.")
    return value


def configured_max_calls_per_phone() -> int:
    raw = os.environ.get("PUBLIC_MAX_CALLS_PER_PHONE", "1").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("PUBLIC_MAX_CALLS_PER_PHONE must be an integer.") from exc
    if value < 1:
        raise RuntimeError("PUBLIC_MAX_CALLS_PER_PHONE must be at least 1.")
    return value


def configured_openai_max_calls(default: int) -> int:
    raw = os.environ.get("OPENAI_TRACE_MAX_CALLS", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("OPENAI_TRACE_MAX_CALLS must be an integer.") from exc
    return max(0, value)


def init_schema() -> None:
    max_calls = configured_max_calls()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public_sessions (
                id uuid PRIMARY KEY,
                token_hash text NOT NULL UNIQUE,
                language text,
                phone_ciphertext text,
                phone_hash text,
                own_number_confirmed boolean NOT NULL DEFAULT false,
                future_calls_authorized boolean NOT NULL DEFAULT false,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS public_sessions_phone_hash_unique
            ON public_sessions(phone_hash)
            WHERE phone_hash IS NOT NULL
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public_budget (
                id smallint PRIMARY KEY CHECK (id = 1),
                max_calls integer NOT NULL CHECK (max_calls >= 0),
                reserved_calls integer NOT NULL DEFAULT 0 CHECK (reserved_calls >= 0),
                consumed_calls integer NOT NULL DEFAULT 0 CHECK (consumed_calls >= 0),
                openai_consumed integer NOT NULL DEFAULT 0 CHECK (openai_consumed >= 0),
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            INSERT INTO public_budget(id, max_calls)
            VALUES (1, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (max_calls or 0,),
        )
        if max_calls is not None:
            cur.execute(
                """
                UPDATE public_budget
                SET max_calls = %s, updated_at = now()
                WHERE id = 1
                """,
                (max_calls,),
            )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public_reservations (
                id uuid PRIMARY KEY,
                session_id uuid NOT NULL REFERENCES public_sessions(id) ON DELETE CASCADE,
                scheduled_for timestamptz NOT NULL,
                future_message text,
                status text NOT NULL,
                slot_reserved boolean NOT NULL DEFAULT true,
                call_id text,
                call_status text,
                delivery_outcome text,
                summary text,
                transcript_json jsonb,
                failure_json jsonb,
                relationship_trace text,
                trace_status text,
                trace_model text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                dispatch_started_at timestamptz,
                completed_at timestamptz
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS public_reservations_one_active
            ON public_reservations(session_id)
            WHERE status IN ('pending', 'dispatching')
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS public_reservations_due_idx
            ON public_reservations(status, scheduled_for)
            """
        )
        conn.commit()


def ensure_session(token: str) -> dict[str, Any]:
    digest = token_hash(token)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public_sessions(id, token_hash)
            VALUES (%s, %s)
            ON CONFLICT (token_hash) DO NOTHING
            """,
            (uuid4(), digest),
        )
        cur.execute("SELECT * FROM public_sessions WHERE token_hash = %s", (digest,))
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("Could not create public session.")
    return row


def profile_status(session_id: UUID | str) -> dict[str, Any]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT language, phone_ciphertext, own_number_confirmed,
                   future_calls_authorized
            FROM public_sessions WHERE id = %s
            """,
            (session_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("Public session does not exist.")
    completed = bool(
        row["language"] in {"en", "ja"}
        and row["phone_ciphertext"]
        and row["own_number_confirmed"] is True
        and row["future_calls_authorized"] is True
    )
    return {
        "completed": completed,
        "language": row["language"] if completed else None,
        "phone_registered": bool(completed),
    }


def save_profile(
    session_id: UUID | str,
    *,
    language: object,
    phone: object,
    own_number_confirmed: object,
    future_calls_authorized: object,
) -> dict[str, Any]:
    if language not in {"en", "ja"}:
        raise ValidationError("Choose English or Japanese.")
    if own_number_confirmed is not True:
        raise ValidationError("Confirm that this is your own phone number.")
    if future_calls_authorized is not True:
        raise ValidationError("Confirm that CALL-E may deliver your scheduled future call.")
    normalized = normalize_phone(phone)
    fingerprint = phone_fingerprint(normalized)
    ciphertext = encrypt_phone(normalized)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT language, phone_ciphertext FROM public_sessions WHERE id = %s FOR UPDATE",
            (session_id,),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError("Public session does not exist.")
        if existing["phone_ciphertext"] or existing["language"]:
            raise ProfileExistsError("A completed profile already exists for this browser.")
        try:
            cur.execute(
                """
                UPDATE public_sessions
                SET language = %s,
                    phone_ciphertext = %s,
                    phone_hash = %s,
                    own_number_confirmed = true,
                    future_calls_authorized = true,
                    updated_at = now()
                WHERE id = %s
                """,
                (language, ciphertext, fingerprint, session_id),
            )
            conn.commit()
        except psycopg.errors.UniqueViolation as exc:
            conn.rollback()
            raise PhoneAlreadyUsedError(
                "This phone number has already been used for the limited public trial."
            ) from exc
    return profile_status(session_id)


def budget_snapshot() -> dict[str, int]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT max_calls, reserved_calls, consumed_calls, openai_consumed FROM public_budget WHERE id = 1"
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("Public trial budget is not initialized.")
    remaining = max(0, row["max_calls"] - row["reserved_calls"] - row["consumed_calls"])
    return {
        "max_calls": row["max_calls"],
        "reserved_calls": row["reserved_calls"],
        "consumed_calls": row["consumed_calls"],
        "slots_remaining": remaining,
        "openai_consumed": row["openai_consumed"],
    }


def _public_pending(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "status": row["status"],
        "scheduled_for": row["scheduled_for"].isoformat(),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "future_message": row.get("future_message"),
        "delivery": {
            "mode": "public-live",
            "state": "scheduled" if row["status"] == "pending" else row["status"],
            "coherent": row["status"] in {"pending", "dispatching"},
            "error_code": None,
        },
    }


def state_for_session(session_id: UUID | str) -> dict[str, Any]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM public_reservations
            WHERE session_id = %s AND status IN ('pending', 'dispatching')
            ORDER BY created_at DESC LIMIT 1
            """,
            (session_id,),
        )
        pending = cur.fetchone()
        cur.execute(
            """
            SELECT scheduled_for, future_message, status, call_status,
                   delivery_outcome, summary, failure_json, relationship_trace,
                   completed_at, dispatch_started_at
            FROM public_reservations
            WHERE session_id = %s
              AND dispatch_started_at IS NOT NULL
              AND status IN ('completed', 'failed', 'canceled')
            ORDER BY COALESCE(completed_at, dispatch_started_at) DESC
            LIMIT 50
            """,
            (session_id,),
        )
        history_rows = cur.fetchall()
        cur.execute(
            """
            SELECT count(*) AS n
            FROM public_reservations
            WHERE session_id = %s AND status = 'completed'
            """,
            (session_id,),
        )
        completed_count = int(cur.fetchone()["n"])

    history: list[dict[str, Any]] = []
    for row in history_rows:
        occurred = row["completed_at"] or row["dispatch_started_at"]
        failure = row.get("failure_json") or {}
        history.append(
            {
                "occurred_at": occurred.isoformat() if occurred else None,
                "scheduled_for": row["scheduled_for"].isoformat(),
                "status": row["status"],
                "call_status": row.get("call_status"),
                "delivery_outcome": row.get("delivery_outcome"),
                "future_message": row.get("future_message"),
                "summary": row.get("summary"),
                "trace": row.get("relationship_trace"),
                "failure": failure.get("message") or failure.get("type"),
            }
        )
    return {
        "pending": _public_pending(pending),
        "history": history,
        "completed_call_count": completed_count,
        "trial": budget_snapshot(),
    }


def create_reservation(
    session_id: UUID | str,
    *,
    scheduled_for: datetime,
    future_message: str | None,
) -> dict[str, Any]:
    message = (future_message or "").strip()[:500] or None
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT language, phone_ciphertext, own_number_confirmed, future_calls_authorized
            FROM public_sessions WHERE id = %s FOR UPDATE
            """,
            (session_id,),
        )
        profile = cur.fetchone()
        if profile is None or not (
            profile["language"] in {"en", "ja"}
            and profile["phone_ciphertext"]
            and profile["own_number_confirmed"]
            and profile["future_calls_authorized"]
        ):
            raise ValidationError("Complete onboarding before reserving a call.")
        cur.execute(
            """
            SELECT id FROM public_reservations
            WHERE session_id = %s AND status IN ('pending', 'dispatching')
            FOR UPDATE
            """,
            (session_id,),
        )
        if cur.fetchone() is not None:
            raise PendingExistsError("You already have one future call reserved.")
        cur.execute(
            """
            SELECT count(*) AS n
            FROM public_reservations
            WHERE session_id = %s AND dispatch_started_at IS NOT NULL
            """,
            (session_id,),
        )
        attempts = int(cur.fetchone()["n"])
        if attempts >= configured_max_calls_per_phone():
            raise TrialAlreadyUsedError(
                "This phone number has already used its available real-call trial."
            )
        cur.execute("SELECT * FROM public_budget WHERE id = 1 FOR UPDATE")
        budget = cur.fetchone()
        if budget is None:
            raise RuntimeError("Public trial budget is not initialized.")
        if budget["reserved_calls"] + budget["consumed_calls"] >= budget["max_calls"]:
            raise CapacityReachedError(
                "The limited public trial has reached its available real-call capacity."
            )
        reservation_id = uuid4()
        cur.execute(
            """
            INSERT INTO public_reservations(
                id, session_id, scheduled_for, future_message, status, slot_reserved
            ) VALUES (%s, %s, %s, %s, 'pending', true)
            RETURNING *
            """,
            (reservation_id, session_id, scheduled_for, message),
        )
        reservation = cur.fetchone()
        cur.execute(
            """
            UPDATE public_budget
            SET reserved_calls = reserved_calls + 1, updated_at = now()
            WHERE id = 1
            """
        )
        conn.commit()
    return _public_pending(reservation) or {}


def change_reservation(
    session_id: UUID | str,
    *,
    scheduled_for: datetime,
) -> dict[str, Any]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM public_reservations
            WHERE session_id = %s AND status = 'pending'
            FOR UPDATE
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise NoPendingError("There is no pending call that can be changed.")
        cur.execute(
            """
            UPDATE public_reservations
            SET scheduled_for = %s, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (scheduled_for, row["id"]),
        )
        updated = cur.fetchone()
        conn.commit()
    return _public_pending(updated) or {}


def cancel_reservation(session_id: UUID | str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM public_reservations
            WHERE session_id = %s AND status = 'pending'
            FOR UPDATE
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise NoPendingError("There is no pending call to cancel.")
        if row["slot_reserved"]:
            cur.execute("SELECT id FROM public_budget WHERE id = 1 FOR UPDATE")
            cur.execute(
                """
                UPDATE public_budget
                SET reserved_calls = GREATEST(0, reserved_calls - 1), updated_at = now()
                WHERE id = 1
                """
            )
        cur.execute(
            """
            UPDATE public_reservations
            SET status = 'canceled', slot_reserved = false,
                updated_at = now(), completed_at = now()
            WHERE id = %s
            """,
            (row["id"],),
        )
        conn.commit()


def claim_due_reservation() -> dict[str, Any] | None:
    """Atomically claim one due reservation and consume its one real-call slot.

    The slot moves from reserved -> consumed *before* any external CALL-E request.
    If the process crashes after this point, the row remains ``dispatching`` and is
    never automatically retried, which is deliberately conservative for a public
    phone-calling trial.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.*, s.language, s.phone_ciphertext
            FROM public_reservations r
            JOIN public_sessions s ON s.id = r.session_id
            WHERE r.status = 'pending' AND r.scheduled_for <= now()
            ORDER BY r.scheduled_for ASC
            FOR UPDATE OF r SKIP LOCKED
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None:
            conn.commit()
            return None
        cur.execute("SELECT * FROM public_budget WHERE id = 1 FOR UPDATE")
        if row["slot_reserved"]:
            cur.execute(
                """
                UPDATE public_budget
                SET reserved_calls = GREATEST(0, reserved_calls - 1),
                    consumed_calls = consumed_calls + 1,
                    updated_at = now()
                WHERE id = 1
                """
            )
        cur.execute(
            """
            UPDATE public_reservations
            SET status = 'dispatching', slot_reserved = false,
                dispatch_started_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (row["id"],),
        )
        conn.commit()
    row["phone_e164"] = decrypt_phone(row["phone_ciphertext"])
    return row


def continuity_rows(session_id: UUID | str, limit: int = 8) -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT completed_at, summary, relationship_trace
            FROM public_reservations
            WHERE session_id = %s AND status = 'completed'
              AND (summary IS NOT NULL OR relationship_trace IS NOT NULL)
            ORDER BY completed_at DESC NULLS LAST
            LIMIT %s
            """,
            (session_id, limit),
        )
        rows = cur.fetchall()
    rows.reverse()
    return rows


def persist_dispatch_result(
    reservation_id: UUID | str,
    *,
    status: str,
    call_status: str | None,
    delivery_outcome: str,
    call_id: str | None,
    summary: str | None,
    transcript: list[dict[str, Any]],
    failure: dict[str, Any] | None,
) -> None:
    terminal_status = "completed" if status == "completed" else "failed"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public_reservations
            SET status = %s,
                call_status = %s,
                delivery_outcome = %s,
                call_id = %s,
                summary = %s,
                transcript_json = %s,
                failure_json = %s,
                completed_at = now(),
                updated_at = now()
            WHERE id = %s AND status = 'dispatching'
            """,
            (
                terminal_status,
                call_status,
                delivery_outcome,
                call_id,
                summary,
                Jsonb(transcript),
                Jsonb(failure) if failure is not None else None,
                reservation_id,
            ),
        )
        conn.commit()


def reserve_openai_trace_slot() -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM public_budget WHERE id = 1 FOR UPDATE")
        budget = cur.fetchone()
        if budget is None:
            raise RuntimeError("Public trial budget is not initialized.")
        cap = configured_openai_max_calls(int(budget["max_calls"]))
        if cap <= 0 or budget["openai_consumed"] >= cap:
            conn.commit()
            return False
        cur.execute(
            """
            UPDATE public_budget
            SET openai_consumed = openai_consumed + 1, updated_at = now()
            WHERE id = 1
            """
        )
        conn.commit()
        return True


def persist_trace_result(
    reservation_id: UUID | str,
    *,
    status: str,
    trace_content: str | None = None,
    model: str | None = None,
) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public_reservations
            SET relationship_trace = %s,
                trace_status = %s,
                trace_model = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (trace_content, status, model, reservation_id),
        )
        conn.commit()


def get_dispatch_result(reservation_id: UUID | str) -> dict[str, Any] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM public_reservations WHERE id = %s", (reservation_id,))
        return cur.fetchone()
