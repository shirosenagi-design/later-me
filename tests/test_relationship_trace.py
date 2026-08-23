from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from relationship_trace import (
    RELATIONSHIP_TRACE_POLICY,
    RelationshipTraceStore,
    TraceDecision,
    _validate_decision,
    request_openai_decision,
)


def fake_completed(payload: dict) -> dict:
    assert payload["model"] == "gpt-5.6-terra"
    assert payload["store"] is False
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"leave_trace": True, "trace_content": "また今度。"},
                            ensure_ascii=False,
                        ),
                    }
                ],
            }
        ],
    }


class RelationshipTraceTests(unittest.TestCase):
    def test_policy_rejects_gamified_relationship_progression(self) -> None:
        lowered = RELATIONSHIP_TRACE_POLICY.lower()
        self.assertIn("call count", lowered)
        self.assertIn("intimacy points", lowered)
        self.assertIn("leaving nothing", lowered)
        self.assertIn("not automatically the more considerate choice", lowered)
        self.assertIn("do not default either", lowered)
        self.assertIn("counseling", lowered)

    def test_no_trace_discards_stray_content(self) -> None:
        decision = _validate_decision(
            {"leave_trace": False, "trace_content": "system accidentally wrote this"}
        )
        self.assertEqual(decision, TraceDecision(False, None))

    def test_structured_output_is_parsed(self) -> None:
        decision = request_openai_decision(
            {"preferred_language": "ja"},
            api_key="synthetic-test-key",
            model="gpt-5.6-terra",
            post_json=fake_completed,
        )
        self.assertEqual(decision, TraceDecision(True, "また今度。"))

    def test_store_public_items_contains_only_visible_traces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-traces-") as temporary:
            store = RelationshipTraceStore(Path(temporary))
            store.save(
                call_id="call-hidden",
                source_digest="a",
                occurred_at="2026-08-23T01:00:00+09:00",
                preferred_language="ja",
                decision=TraceDecision(False, None),
                model="gpt-5.6-terra",
            )
            store.save(
                call_id="call-visible",
                source_digest="b",
                occurred_at="2026-08-23T02:00:00+09:00",
                preferred_language="ja",
                decision=TraceDecision(True, "また今度。"),
                model="gpt-5.6-terra",
            )
            self.assertEqual(
                store.public_items(),
                [{"occurred_at": "2026-08-23T02:00:00+09:00", "content": "また今度。"}],
            )


if __name__ == "__main__":
    unittest.main()
