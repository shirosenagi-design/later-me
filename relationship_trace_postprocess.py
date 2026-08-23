"""Independent post-call Relationship Trace worker.

The CALL-E phone process has already returned before this script is launched.
OpenAI/Relationship Trace imports are deliberately lazy so a broken optional
trace module cannot interfere with phone dispatch startup.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


COMPLETED_FILE = Path("data") / "completed_calls.jsonl"
MEMORY_ROOT = Path("data") / "usual_ai"
TRACE_ROOT = Path("data") / "relationship_trace"
PROFILE_ROOT = Path("data") / "profile"


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone.")
    return parsed


def load_results_since(path: Path, since: datetime) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    selected: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict):
                continue

            completed_raw = value.get("completed_at_local")
            if not isinstance(completed_raw, str):
                continue
            try:
                completed_at = parse_timestamp(completed_raw)
            except (TypeError, ValueError):
                continue

            if completed_at >= since:
                selected.append(value)

    selected.sort(key=lambda item: item.get("completed_at_local") or "")
    return selected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True)
    parser.add_argument(
        "--completed-file",
        default=str(COMPLETED_FILE),
        help="Override only for diagnostics.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Selection-only validation. Never imports OpenAI trace modules.",
    )
    args = parser.parse_args(argv)

    since = parse_timestamp(args.since)
    results = load_results_since(Path(args.completed_file), since)

    if args.self_test:
        print("RELATIONSHIP_TRACE_POSTPROCESS_SELF_TEST=PASS")
        print("SELECTED_RESULTS:", len(results))
        print("OPENAI_REQUEST_SENT=NO")
        print("REAL_PHONE_CALL=NO")
        return 0

    if not results:
        print("RELATIONSHIP_TRACE_POSTPROCESS=SKIPPED_NO_NEW_RESULT")
        print("OPENAI_REQUEST_SENT=NO")
        return 0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("RELATIONSHIP_TRACE_POSTPROCESS=SKIPPED_NO_OPENAI_KEY")
        return 0

    # Lazy optional imports: these can fail only after phone dispatch has finished.
    try:
        from relationship_trace import infer_and_persist_relationship_trace
        from user_profile import ProfileError, UserProfileStore
    except Exception as exc:
        print("RELATIONSHIP_TRACE_POSTPROCESS=FAILED_IMPORT")
        print("FAILURE_TYPE:", type(exc).__name__)
        return 1

    try:
        profile = UserProfileStore(PROFILE_ROOT).require_complete()
    except ProfileError as exc:
        print("RELATIONSHIP_TRACE_POSTPROCESS=FAILED_PROFILE")
        print("FAILURE_TYPE:", type(exc).__name__)
        return 1

    failures = 0
    processed = 0

    for result in results:
        call_id = str(result.get("call_id") or "").strip()
        if not call_id:
            print("RELATIONSHIP_TRACE_ITEM=SKIPPED_MISSING_CALL_ID")
            continue

        try:
            outcome = infer_and_persist_relationship_trace(
                result,
                language=profile.language,
                memory_root=MEMORY_ROOT,
                trace_root=TRACE_ROOT,
                api_key=api_key,
                enabled=True,
            )
        except Exception as exc:
            failures += 1
            print("RELATIONSHIP_TRACE_ITEM=FAILED")
            print("CALL_ID:", call_id)
            print("FAILURE_TYPE:", type(exc).__name__)
            continue

        processed += 1
        print("RELATIONSHIP_TRACE_ITEM=" + outcome.status.upper())
        print("CALL_ID:", call_id)
        if outcome.status in {"processed", "already_processed"}:
            print("VISIBLE:", "YES" if outcome.leave_trace else "NO")
            if outcome.leave_trace and outcome.trace_content:
                print("TRACE_CONTENT:", outcome.trace_content)

    if failures:
        print("RELATIONSHIP_TRACE_POSTPROCESS=PARTIAL_FAILURE")
        print("PROCESSED:", processed)
        print("FAILED:", failures)
        return 1

    print("RELATIONSHIP_TRACE_POSTPROCESS=PASS")
    print("PROCESSED:", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
