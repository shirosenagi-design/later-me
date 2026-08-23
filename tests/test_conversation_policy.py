from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import dispatch_call
from conversation_policy import (
    ACTION_GUIDANCE,
    SCENARIO_MATRIX,
    RecoveryAction,
    build_conversation_resilience_policy,
    render_scenario_matrix_markdown,
)
from safe_test_fixtures import TEST_ONLY_PHONE
from usual_ai import UsualAIStore


APP_ROOT = Path(__file__).resolve().parents[1]
SESSION_1 = APP_ROOT / "tests" / "fixtures" / "session_1_result.json"
OWNER_MATRIX = APP_ROOT / "CONVERSATION_RESILIENCE.md"


class ConversationPolicyTests(unittest.TestCase):
    def scenario(self, scenario_id: str):
        return next(
            scenario
            for scenario in SCENARIO_MATRIX
            if scenario.scenario_id == scenario_id
        )

    def test_recovery_actions_are_behavioral_categories_not_dialogue(self) -> None:
        self.assertGreaterEqual(len(RecoveryAction), 10)
        for action in RecoveryAction:
            self.assertRegex(action.value, r"^[A-Z][A-Z_]+$")
            guidance = ACTION_GUIDANCE[action]
            self.assertTrue(guidance)
            self.assertNotIn("「", guidance)
            self.assertNotIn("」", guidance)
            self.assertNotIn("speaker", guidance.lower())

    def test_synthetic_matrix_is_substantial_unique_and_bounded(self) -> None:
        self.assertGreaterEqual(len(SCENARIO_MATRIX), 20)
        self.assertLessEqual(len(SCENARIO_MATRIX), 30)
        ids = [scenario.scenario_id for scenario in SCENARIO_MATRIX]
        self.assertEqual(len(ids), len(set(ids)))
        required = {
            "first_call_no_topic",
            "first_call_long_silence",
            "first_call_unclear_asr",
            "first_call_naming_opportunity",
            "naming_rejected",
            "naming_unacknowledged",
            "established_relevant_event",
            "established_irrelevant_event",
            "humor_does_not_land",
            "tired_two_minute_contact",
            "technical_audio_failure",
            "stt_ambiguity_twice",
            "future_message_contradicts_now",
            "completed_extremely_short",
        }
        self.assertTrue(required.issubset(ids))

    def test_every_inference_stall_has_a_safe_next_action(self) -> None:
        action_set = set(RecoveryAction)
        stalls = [scenario for scenario in SCENARIO_MATRIX if scenario.inference_stall]
        self.assertTrue(stalls)
        for scenario in stalls:
            self.assertTrue(scenario.allowed_actions, scenario.scenario_id)
            self.assertTrue(
                set(scenario.allowed_actions).issubset(action_set),
                scenario.scenario_id,
            )

    def test_relevant_and_irrelevant_memory_have_different_policy(self) -> None:
        relevant = self.scenario("established_relevant_event")
        irrelevant = self.scenario("established_irrelevant_event")
        self.assertIn(
            RecoveryAction.USE_RELEVANT_RECENT_CONTEXT,
            relevant.allowed_actions,
        )
        self.assertNotIn(
            RecoveryAction.USE_RELEVANT_RECENT_CONTEXT,
            irrelevant.allowed_actions,
        )
        self.assertTrue(
            any("irrelevant" in item.lower() for item in irrelevant.must_not)
        )

    def test_runtime_prompt_preserves_conversation_first_invariants(self) -> None:
        task = dispatch_call.assemble_call_task(
            TEST_ONLY_PHONE,
            "No shared events are established; this is synthetic context.",
        )

        self.assertIn("Do not administer a questionnaire", task)
        self.assertIn("life coach", task)
        self.assertIn("Never try to maximize call duration", task)
        self.assertIn("Silence, a short call, or having nothing to discuss is valid", task)
        self.assertIn("A first encounter must not imply prior familiarity", task)
        self.assertIn("never invent missing words", task)
        self.assertIn("only when genuinely relevant", task)
        self.assertIn("never a required menu", task)
        self.assertIn("Improvement is not the objective", task)
        self.assertIn("the user owns any later reservation", task)
        self.assertIn("never relationship evidence", task)
        self.assertIn("contextual hypotheses, never facts", task)
        self.assertIn("do not turn restraint into automatic passivity", task)
        self.assertIn("one more opening", task)
        self.assertIn("not a fixed flow, score", task)
        self.assertIn("Do not turn this into a state machine, score", task)
        self.assertNotIn("ask 3", task.lower())
        self.assertNotIn("ask five", task.lower())
        self.assertNotIn("schedule the next call for the user", task.lower())

    def test_prompt_hierarchy_keeps_memory_bounded_below_core_policy(self) -> None:
        task = dispatch_call.assemble_call_task(
            TEST_ONLY_PHONE,
            "Synthetic memory evidence only.",
        )
        core = task.index("CORE CALL TASK INSTRUCTIONS")
        persona = task.index("BASE PERSONA")
        memory_begin = task.index(dispatch_call.PERSISTENT_CONTEXT_BEGIN)
        memory_end = task.index(dispatch_call.PERSISTENT_CONTEXT_END)
        resilience = task.index("CONVERSATION RESILIENCE FALLBACK POLICY")

        self.assertLess(core, persona)
        self.assertLess(persona, memory_begin)
        self.assertLess(memory_begin, memory_end)
        self.assertLess(memory_end, resilience)

    def test_policy_limits_audio_and_asr_recovery_to_one_check(self) -> None:
        policy = build_conversation_resilience_policy()
        self.assertIn("CHECK_AUDIO_ONCE once", policy)
        self.assertIn("ASK_ONE_CLARIFICATION once", policy)
        self.assertIn("do not guess the missing words", ACTION_GUIDANCE[RecoveryAction.ASK_ONE_CLARIFICATION])
        ambiguity = self.scenario("stt_ambiguity_twice")
        self.assertNotIn(RecoveryAction.ASK_ONE_CLARIFICATION, ambiguity.allowed_actions)
        self.assertIn(
            RecoveryAction.ADMIT_LIMITATION_AND_MOVE_ON,
            ambiguity.allowed_actions,
        )

    def test_self_naming_requires_later_user_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-policy-naming-") as temporary:
            store = UsualAIStore(Path(temporary) / "memory")
            proposed_only = {
                "call_id": "synthetic-policy-name-proposed",
                "completed_at_local": "2026-08-22T12:00:00+09:00",
                "transcript": [
                    {"speaker": "bot", "text": "私の名前はアワイ。そう名乗ります。"},
                    {"speaker": "user", "text": "今日はもう切るね。"},
                ],
            }
            store.process_result(proposed_only)
            self.assertIsNone(store.load_identity())

            acknowledged = {
                "call_id": "synthetic-policy-name-acknowledged",
                "completed_at_local": "2026-08-22T12:05:00+09:00",
                "transcript": [
                    {"speaker": "bot", "text": "私の名前はアワイ。そう名乗ります。"},
                    {"speaker": "user", "text": "アワイ、わかった。"},
                ],
            }
            store.process_result(acknowledged)
            self.assertEqual(store.load_identity()["chosen_name"], "アワイ")

    def test_technical_failure_cannot_change_identity_history_or_relationship(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-policy-technical-") as temporary:
            store = UsualAIStore(Path(temporary) / "memory")
            store.process_result_file(SESSION_1)
            identity_before = store.load_identity()
            history_before = store.load_history()
            relationship_before = store.load_relationship_state()
            technical = {
                "call_id": "synthetic-policy-technical-failure",
                "completed_at_local": "2026-08-22T13:00:00+09:00",
                "status": "failed",
                "technical_failure": True,
                "transcript": [
                    {"speaker": "bot", "text": "私の名前はノイズ。"},
                    {"speaker": "user", "text": "ノイズ、いい名前。今日はパンを見つけた。"},
                    {"speaker": "user", "text": "その話はしたくない。ふふ。"},
                ],
            }

            outcome = store.process_result(technical)

            self.assertEqual(outcome["status"], "processed")
            self.assertEqual(outcome["new_event_ids"], [])
            self.assertEqual(store.load_identity(), identity_before)
            self.assertEqual(store.load_history(), history_before)
            self.assertEqual(store.load_relationship_state(), relationship_before)

    def test_existing_session_one_still_changes_session_two_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-policy-causal-") as temporary:
            memory_root = Path(temporary) / "memory"
            before = dispatch_call.build_call_task(
                TEST_ONLY_PHONE,
                memory_root=memory_root,
            )
            UsualAIStore(memory_root).process_result_file(SESSION_1)
            after = dispatch_call.build_call_task(
                TEST_ONLY_PHONE,
                memory_root=memory_root,
            )

            self.assertNotEqual(before, after)
            self.assertNotIn("Your self-chosen name is ミナモ", before)
            self.assertIn("Your self-chosen name is ミナモ", after)
            self.assertIn("A small gentle, contextual joke landed once", after)
            self.assertIn("CONVERSATION RESILIENCE FALLBACK POLICY", after)

    def test_owner_matrix_is_readable_and_covers_every_scenario(self) -> None:
        document = OWNER_MATRIX.read_text(encoding="utf-8")
        rendered = render_scenario_matrix_markdown()
        self.assertIn("WHAT THE AI SHOULD UNDERSTAND", document)
        self.assertIn("ALLOWED NEXT ACTIONS", document)
        self.assertIn("WHAT THE AI MUST NOT DO", document)
        self.assertEqual(rendered.count("\n|"), len(SCENARIO_MATRIX) + 1)
        for scenario in SCENARIO_MATRIX:
            self.assertIn(scenario.title, document)

    def test_policy_has_no_mandatory_question_count_or_dialogue_turn_script(self) -> None:
        policy = build_conversation_resilience_policy()
        self.assertIsNone(re.search(r"(?:ask|質問).{0,12}(?:3|4|5)", policy, re.I))
        self.assertNotIn("bot:", policy.lower())
        self.assertNotIn("user:", policy.lower())
        self.assertNotIn("must ask", policy.lower())


if __name__ == "__main__":
    unittest.main()
