"""CLI for post-call memory updates and next-call context generation."""
from __future__ import annotations

import argparse
from pathlib import Path

from qa_isolation import require_isolated_memory_root
from usual_ai import UsualAIStore


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_MEMORY_ROOT = APP_ROOT / "data" / "usual_ai"


def _memory_root(value: str | None, test_mode: bool) -> Path:
    if test_mode:
        if not value:
            raise ValueError("--test-mode requires an explicit --memory-root.")
        return require_isolated_memory_root(value, app_root=APP_ROOT)
    return Path(value).resolve() if value else DEFAULT_MEMORY_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update or read the persistent CALL-E usual-AI layer."
    )
    parser.add_argument("--memory-root")
    parser.add_argument("--test-mode", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="Consume one saved call result.")
    update.add_argument("result", type=Path)

    context = subparsers.add_parser("context", help="Generate concise next-call context.")
    context.add_argument("--future-message")

    args = parser.parse_args()
    store = UsualAIStore(_memory_root(args.memory_root, args.test_mode))

    if args.command == "update":
        outcome = store.process_result_file(args.result)
        print("USUAL_AI_UPDATE=" + outcome["status"].upper())
        print("call_id:", outcome["call_id"])
        print("new_events:", len(outcome["new_event_ids"]))
        print("AI_IDENTITY_PRESENT:", "YES" if store.load_identity() else "NO")
        return

    print(store.generate_next_call_context(args.future_message))


if __name__ == "__main__":
    main()
