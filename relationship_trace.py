"""OpenAI-backed inference for optional, user-visible relationship traces.

Internal call execution history remains exhaustive elsewhere. This module decides
whether one call attempt should leave a *visible* trace in the user's "これまで"
view. A missing trace is a normal outcome, not an error.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import httpx

from usual_ai import BASE_PERSONA, UsualAIStore


SCHEMA_VERSION = 1
DEFAULT_MODEL = "gpt-5.6-terra"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_TRACE_CHARS = 280
MAX_TRANSCRIPT_TURNS = 30
MAX_TRANSCRIPT_CHARS = 6_000
MAX_SHARED_EVENTS = 10
MAX_RECENT_VISIBLE_TRACES = 5

TRACE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "leave_trace": {"type": "boolean"},
        "trace_content": {
            "anyOf": [
                {"type": "string", "maxLength": MAX_TRACE_CHARS},
                {"type": "null"},
            ]
        },
    },
    "required": ["leave_trace", "trace_content"],
    "additionalProperties": False,
}

RELATIONSHIP_TRACE_POLICY = """
You are deciding whether CALL-E should leave one user-visible relationship trace
because of the most recent phone-call attempt.

A relationship trace is NOT:
- an exhaustive call log;
- a customer-support or system-status report;
- a counseling note or assessment of the user;
- a romance-game progression reward;
- a way to maximize retention, conversation time, spending, streaks, or attachment.

Decision principles:
1. Leaving nothing is a complete and normal outcome. Do not create a trace merely
   because a call happened, failed, was missed, or completed.
2. Never use call count, usage frequency, affection/intimacy points, streaks,
   spending, paid usage, or unlock thresholds as reasons to create a trace.
3. Relationship evidence is context for judgment, never a score or progression bar.
4. A close relationship does not require a trace every time. A newer relationship
   does not mechanically forbid one if the specific moment genuinely warrants it.
   Leaving nothing is not automatically the more considerate choice. When a specific,
   supported interaction was meaningful and a brief trace would naturally carry that
   care or shared moment forward, leaving one may be appropriate. Do not default either
   to leaving a trace or to withholding one.
5. For a missed/unanswered call, decide whether this particular AI, in this
   particular relationship and reservation context, would naturally leave anything.
   Often the considerate choice is to leave nothing.
6. A purely technical/provider failure should not be turned into artificial
   relationship content.
7. Do not diagnose, evaluate, or summarize the user's emotional or mental state.
   Avoid "today you seemed..." style counseling records.
8. Never expose implementation vocabulary such as recipient, bot, API, provider,
   goal achieved, completion flag, transcript retrieval, or confidence score.
9. Do not pretend to be human. Write as the continuing AI persona represented in
   the supplied context.
10. Respect distance and boundaries. Do not use a trace to pressure the user to
    return, reply, talk longer, pay, or become closer.
11. Preserve time direction: past reservation -> AI -> present/future user. Never
    imply that information will be sent backward to the past self.
12. Use the preferred language supplied in the context.
13. If a trace is appropriate, make it brief and natural: something this AI chose
    to leave, not a report about the call.
14. If no trace should remain, return leave_trace=false and trace_content=null.
""".strip()


@dataclass(frozen=True)
class TraceDecision:
    leave_trace: bool
    trace_content: str | None


@dataclass(frozen=True)
class TraceOutcome:
    status: str
    leave_trace: bool = False
    trace_content: str | None = None
    model: str | None = None


class RelationshipTraceStore:
    """Idempotent storage for inferred decisions, separate from call execution logs."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.decisions_path = self.root / "decisions.json"

    def _load(self) -> dict[str, Any]:
        if not self.decisions_path.exists():
            return {"schema_version": SCHEMA_VERSION, "calls": {}}
        value = json.loads(self.decisions_path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or not isinstance(value.get("calls"), dict):
            raise ValueError("Relationship trace decision store is malformed.")
        return value

    def _write(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.decisions_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.decisions_path)

    def get(self, call_id: str) -> dict[str, Any] | None:
        return self._load()["calls"].get(call_id)

    def save(
        self,
        *,
        call_id: str,
        source_digest: str,
        occurred_at: str,
        preferred_language: str,
        decision: TraceDecision,
        model: str,
    ) -> dict[str, Any]:
        payload = self._load()
        existing = payload["calls"].get(call_id)
        if existing is not None:
            if existing.get("source_digest") != source_digest:
                raise ValueError("A different call artifact already used this trace call_id.")
            return existing

        entry = {
            "call_id": call_id,
            "source_digest": source_digest,
            "occurred_at": occurred_at,
            "preferred_language": preferred_language,
            "leave_trace": decision.leave_trace,
            "trace_content": decision.trace_content,
            "model": model,
            "decided_at": datetime.now().astimezone().isoformat(),
        }
        payload["calls"][call_id] = entry
        self._write(payload)
        return entry

    def recent_visible(self, limit: int = MAX_RECENT_VISIBLE_TRACES) -> list[dict[str, Any]]:
        entries = [
            value
            for value in self._load()["calls"].values()
            if value.get("leave_trace") is True and value.get("trace_content")
        ]
        entries.sort(key=lambda item: item.get("occurred_at") or "", reverse=True)
        return entries[:limit]

    def public_items(self) -> list[dict[str, Any]]:
        """Only visible relationship traces. Never expose exhaustive call history here."""
        return [
            {
                "occurred_at": item.get("occurred_at"),
                "content": item.get("trace_content"),
            }
            for item in self.recent_visible(limit=10_000)
        ]


def _source_digest(result: dict[str, Any]) -> str:
    source = {
        "call_id": result.get("call_id"),
        "status": result.get("status"),
        "delivery_outcome": result.get("delivery_outcome"),
        "scheduled_for": result.get("scheduled_for"),
        "future_message": result.get("future_message"),
        "transcript": result.get("transcript"),
        "failure_details": result.get("failure_details"),
    }
    return hashlib.sha256(
        json.dumps(source, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _bounded_transcript(result: dict[str, Any]) -> list[dict[str, str]]:
    value = result.get("transcript")
    turns = value if isinstance(value, list) else []
    output: list[dict[str, str]] = []
    used = 0
    for turn in turns[:MAX_TRANSCRIPT_TURNS]:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker") or "unknown")[:40]
        text = " ".join(str(turn.get("text") or "").split())
        if not text:
            continue
        remaining = MAX_TRANSCRIPT_CHARS - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[: max(0, remaining - 1)].rstrip() + "…"
        output.append({"speaker": speaker, "text": text})
        used += len(text)
    return output


def build_inference_context(
    result: dict[str, Any],
    *,
    language: str,
    memory_store: UsualAIStore,
    trace_store: RelationshipTraceStore,
) -> dict[str, Any]:
    identity = memory_store.load_identity()
    relationship = memory_store.load_relationship_state()
    history = memory_store.load_history()

    shared_summaries = [
        str(event.get("summary"))
        for event in history[-MAX_SHARED_EVENTS:]
        if isinstance(event, dict) and event.get("summary")
    ]
    hypotheses = {
        name: value.get("hypothesis")
        for name, value in relationship.get("dimensions", {}).items()
        if isinstance(value, dict) and value.get("hypothesis")
    }
    recent_traces = [
        {
            "occurred_at": item.get("occurred_at"),
            "content": item.get("trace_content"),
        }
        for item in trace_store.recent_visible()
    ]

    return {
        "preferred_language": language,
        "persona": {
            "base_persona": BASE_PERSONA,
            "established_identity": identity,
        },
        "relationship_context": {
            "hypotheses": hypotheses,
            "shared_history_evidence": shared_summaries,
            "recent_visible_traces": recent_traces,
        },
        "reservation": {
            "scheduled_for": result.get("scheduled_for"),
            "past_self_message": result.get("future_message"),
        },
        "latest_call": {
            "status": result.get("status"),
            "delivery_outcome": result.get("delivery_outcome"),
            "failure_details": result.get("failure_details"),
            "transcript": _bounded_transcript(result),
        },
    }


def _extract_output_text(response_payload: dict[str, Any]) -> str:
    for item in response_payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    raise RuntimeError("OpenAI response contained no output_text content.")


def _validate_decision(value: dict[str, Any]) -> TraceDecision:
    leave_trace = value.get("leave_trace")
    content = value.get("trace_content")
    if not isinstance(leave_trace, bool):
        raise ValueError("leave_trace must be boolean.")
    if content is not None and not isinstance(content, str):
        raise ValueError("trace_content must be string or null.")
    if isinstance(content, str):
        content = " ".join(content.split()).strip() or None
        if content and len(content) > MAX_TRACE_CHARS:
            raise ValueError("trace_content exceeds the visible trace cap.")
    if leave_trace and not content:
        return TraceDecision(False, None)
    if not leave_trace:
        return TraceDecision(False, None)
    return TraceDecision(True, content)


def request_openai_decision(
    context: dict[str, Any],
    *,
    api_key: str,
    model: str,
    post_json: Callable[..., dict[str, Any]] | None = None,
) -> TraceDecision:
    request_payload = {
        "model": model,
        "store": False,
        "reasoning": {"effort": "medium"},
        "instructions": RELATIONSHIP_TRACE_POLICY,
        "input": json.dumps(context, ensure_ascii=False, indent=2),
        "max_output_tokens": 400,
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "call_e_relationship_trace",
                "description": "Whether one CALL-E moment should leave a visible relationship trace.",
                "strict": True,
                "schema": TRACE_OUTPUT_SCHEMA,
            },
        },
    }

    if post_json is None:
        response = httpx.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=30.0,
        )
        response.raise_for_status()
        response_payload = response.json()
    else:
        response_payload = post_json(request_payload)

    if response_payload.get("status") not in {None, "completed"}:
        raise RuntimeError(
            "OpenAI relationship-trace response did not complete: "
            + str(response_payload.get("status"))
        )
    raw_text = _extract_output_text(response_payload)
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("Structured trace output was not an object.")
    return _validate_decision(parsed)


def _env_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def infer_and_persist_relationship_trace(
    result: dict[str, Any],
    *,
    language: str,
    memory_root: Path | str,
    trace_root: Path | str,
    api_key: str | None = None,
    model: str | None = None,
    post_json: Callable[..., dict[str, Any]] | None = None,
    enabled: bool | None = None,
) -> TraceOutcome:
    is_enabled = (
        _env_enabled(os.environ.get("CALL_E_RELATIONSHIP_TRACE_ENABLED"))
        if enabled is None
        else enabled
    )
    if not is_enabled:
        return TraceOutcome(status="skipped_disabled")

    call_id = str(result.get("call_id") or "").strip()
    if not call_id:
        return TraceOutcome(status="skipped_missing_call_id")

    trace_store = RelationshipTraceStore(trace_root)
    digest = _source_digest(result)
    existing = trace_store.get(call_id)
    if existing is not None:
        if existing.get("source_digest") != digest:
            raise ValueError("A different artifact already used this relationship trace call_id.")
        return TraceOutcome(
            status="already_processed",
            leave_trace=bool(existing.get("leave_trace")),
            trace_content=existing.get("trace_content"),
            model=existing.get("model"),
        )

    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    if not key:
        return TraceOutcome(status="skipped_no_openai_api_key")

    selected_model = model or os.environ.get("OPENAI_RELATIONSHIP_MODEL", DEFAULT_MODEL)
    memory_store = UsualAIStore(memory_root)
    context = build_inference_context(
        result,
        language=language,
        memory_store=memory_store,
        trace_store=trace_store,
    )
    decision = request_openai_decision(
        context,
        api_key=key,
        model=selected_model,
        post_json=post_json,
    )
    occurred_at = str(
        result.get("completed_at_local")
        or result.get("completed_at")
        or datetime.now().astimezone().isoformat()
    )
    trace_store.save(
        call_id=call_id,
        source_digest=digest,
        occurred_at=occurred_at,
        preferred_language=language,
        decision=decision,
        model=selected_model,
    )
    return TraceOutcome(
        status="processed",
        leave_trace=decision.leave_trace,
        trace_content=decision.trace_content,
        model=selected_model,
    )
