from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from usual_ai import UsualAIStore


APP_ROOT = Path(__file__).resolve().parents[1]
SESSION_1 = APP_ROOT / "tests" / "fixtures" / "session_1_result.json"


class UsualAIPersistenceTests(unittest.TestCase):
    @staticmethod
    def _result(call_id: str, transcript: list[dict[str, str]]) -> dict[str, object]:
        return {
            "call_id": call_id,
            "completed_at_local": "2026-08-21T18:08:00+09:00",
            "transcript": transcript,
        }

    def test_session_one_changes_session_two_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-usual-ai-") as temporary:
            store = UsualAIStore(Path(temporary) / "memory")
            before = store.generate_next_call_context()

            outcome = store.process_result_file(SESSION_1)
            identity = store.load_identity()
            history = store.load_history()
            relationship = store.load_relationship_state()
            after = store.generate_next_call_context(
                "昨日の続きを無理に話さなくても大丈夫。"
            )

            self.assertEqual(outcome["status"], "processed")
            self.assertEqual(identity["chosen_name"], "ミナモ")
            self.assertEqual(identity["first_call_id"], "synthetic-call-001")
            self.assertIn("水面", identity["origin_story"])

            event_types = {event["event_type"] for event in history}
            self.assertIn("ai_self_naming", event_types)
            self.assertIn("shared_conversation", event_types)
            self.assertIn("successful_humor", event_types)
            self.assertTrue(all("text" not in event for event in history))
            self.assertNotIn(
                "寄り道というより、パンに呼ばれた感じですね。",
                json.dumps(history, ensure_ascii=False),
            )
            self.assertNotIn(
                "今日は帰り道に小さなパン屋を見つけたんだ。",
                json.dumps(history, ensure_ascii=False),
            )

            dimensions = relationship["dimensions"]
            self.assertEqual(
                dimensions["conversational_distance"]["hypothesis"],
                "gently_familiar",
            )
            self.assertEqual(
                dimensions["humor_style"]["hypothesis"],
                "gentle_contextual_humor_may_be_welcome",
            )
            self.assertNotIn("score", json.dumps(relationship))
            self.assertNotIn("level", json.dumps(relationship))

            self.assertIn("Treat this as a first encounter", before)
            self.assertIn("Do not assume shared humor yet", before)
            self.assertNotIn("ミナモ", before)

            self.assertIn("Your self-chosen name is ミナモ", after)
            self.assertIn("食べもの", after)
            self.assertIn("A small gentle, contextual joke landed once", after)
            self.assertIn("Keep explanations slightly shorter", after)
            self.assertNotIn("パンに呼ばれた感じですね", after)
            self.assertNotIn("小さなパン屋を見つけたんだ", after)
            self.assertNotEqual(before, after)

            repeated = store.process_result_file(SESSION_1)
            self.assertEqual(repeated["status"], "already_processed")
            self.assertEqual(len(store.load_history()), len(history))

    def test_bot_self_naming_without_user_response_does_not_persist_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-usual-ai-") as temporary:
            store = UsualAIStore(Path(temporary) / "memory")
            result = self._result(
                "bot-only-name",
                [
                    {
                        "speaker": "bot",
                        "text": "私の名前はアワイ。そう名乗ることにします。",
                    }
                ],
            )

            first = store.process_result(result)
            repeated = store.process_result(result)

            self.assertEqual(first["status"], "processed")
            self.assertEqual(repeated["status"], "already_processed")
            self.assertIsNone(store.load_identity())
            self.assertNotIn(
                "ai_self_naming",
                {event["event_type"] for event in store.load_history()},
            )

    def test_user_acknowledgement_establishes_bot_selected_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-usual-ai-") as temporary:
            store = UsualAIStore(Path(temporary) / "memory")
            result = self._result(
                "mutually-established-name",
                [
                    {
                        "speaker": "bot",
                        "text": "私の名前はアワイ。会話のあわいから選びました。",
                    },
                    {"speaker": "user", "text": "アワイ、いい名前ですね。"},
                ],
            )

            store.process_result(result)

            identity = store.load_identity()
            self.assertIsNotNone(identity)
            self.assertEqual(identity["chosen_name"], "アワイ")
            identity_event = next(
                event
                for event in store.load_history()
                if event["event_type"] == "ai_self_naming"
            )
            self.assertEqual(identity_event["evidence"]["turn_indices"], [0, 1])
            self.assertEqual(
                identity_event["attributes"]["establishment_evidence"],
                "bot_proposal_then_user_acknowledgement",
            )

    def test_interrupted_technical_call_cannot_persist_bot_only_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-usual-ai-") as temporary:
            store = UsualAIStore(Path(temporary) / "memory")
            result = self._result(
                "interrupted-technical-call",
                [
                    {"speaker": "user", "text": "もしもし、音が途切れています。"},
                    {
                        "speaker": "bot",
                        "text": "私の名前はアワイ。これからそう名乗ります。",
                    },
                ],
            )

            store.process_result(result)

            self.assertIsNone(store.load_identity())
            self.assertNotIn(
                "ai_self_naming",
                {event["event_type"] for event in store.load_history()},
            )

if __name__ == "__main__":
    unittest.main()
