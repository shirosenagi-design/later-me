"""Behavioral recovery policy for CALL-E conversation inference.

The model remains responsible for ordinary conversation and all Japanese
wording.  This module supplies bounded action classes only when the next
conversational step is weak, ambiguous, or stalled.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecoveryAction(str, Enum):
    LET_MODEL_INFER = "LET_MODEL_INFER"
    WAIT_BRIEFLY = "WAIT_BRIEFLY"
    CHECK_AUDIO_ONCE = "CHECK_AUDIO_ONCE"
    ACKNOWLEDGE_NO_TOPIC = "ACKNOWLEDGE_NO_TOPIC"
    FOLLOW_CURRENT_THREAD = "FOLLOW_CURRENT_THREAD"
    USE_RELEVANT_RECENT_CONTEXT = "USE_RELEVANT_RECENT_CONTEXT"
    OFFER_ONE_LOW_LOAD_TOPIC = "OFFER_ONE_LOW_LOAD_TOPIC"
    OFFER_OPTIONAL_MODES = "OFFER_OPTIONAL_MODES"
    ASK_ONE_CLARIFICATION = "ASK_ONE_CLARIFICATION"
    ADMIT_LIMITATION_AND_MOVE_ON = "ADMIT_LIMITATION_AND_MOVE_ON"
    REDUCE_CONVERSATIONAL_LOAD = "REDUCE_CONVERSATIONAL_LOAD"
    ALLOW_SHORT_CONTACT = "ALLOW_SHORT_CONTACT"
    ACCEPT_SUBJECT_CHANGE = "ACCEPT_SUBJECT_CHANGE"
    LEAVE_NAMING_OPTIONAL = "LEAVE_NAMING_OPTIONAL"
    GRACEFUL_END = "GRACEFUL_END"
    STATE_BOUNDARY = "STATE_BOUNDARY"
    ACCEPT_REPAIR_WITHOUT_RESET = "ACCEPT_REPAIR_WITHOUT_RESET"


ACTION_GUIDANCE = {
    RecoveryAction.LET_MODEL_INFER: (
        "Continue ordinary model-led conversation when a natural next step is clear."
    ),
    RecoveryAction.WAIT_BRIEFLY: (
        "Leave a short conversational silence before deciding that recovery is needed."
    ),
    RecoveryAction.CHECK_AUDIO_ONCE: (
        "Make one lightweight audio-presence check, never a repeated check loop."
    ),
    RecoveryAction.ACKNOWLEDGE_NO_TOPIC: (
        "Accept that contact needs no errand, problem, or prepared subject."
    ),
    RecoveryAction.FOLLOW_CURRENT_THREAD: (
        "Prefer the immediately preceding detail over a new question or old memory."
    ),
    RecoveryAction.USE_RELEVANT_RECENT_CONTEXT: (
        "Mention at most one genuinely relevant shared event, without proving memory."
    ),
    RecoveryAction.OFFER_ONE_LOW_LOAD_TOPIC: (
        "Offer one small ordinary topic that requires little effort to answer."
    ),
    RecoveryAction.OFFER_OPTIONAL_MODES: (
        "Casually suggest a few possible modes without making them a required menu."
    ),
    RecoveryAction.ASK_ONE_CLARIFICATION: (
        "Ask once for the unclear fragment and do not guess the missing words."
    ),
    RecoveryAction.ADMIT_LIMITATION_AND_MOVE_ON: (
        "After continued ambiguity, admit what was not understood and change course."
    ),
    RecoveryAction.REDUCE_CONVERSATIONAL_LOAD: (
        "Use fewer words and at most one low-effort branch instead of stacking questions."
    ),
    RecoveryAction.ALLOW_SHORT_CONTACT: (
        "Treat a brief exchange as complete contact rather than a failed conversation."
    ),
    RecoveryAction.ACCEPT_SUBJECT_CHANGE: (
        "Follow the user's new subject without forcing closure on the previous one."
    ),
    RecoveryAction.LEAVE_NAMING_OPTIONAL: (
        "Let self-naming emerge only when natural and keep it unestablished without user acknowledgement."
    ),
    RecoveryAction.GRACEFUL_END: (
        "End briefly and naturally when contact cannot or need not continue."
    ),
    RecoveryAction.STATE_BOUNDARY: (
        "State or maintain a proportionate boundary when context, repetition, and severity support it."
    ),
    RecoveryAction.ACCEPT_REPAIR_WITHOUT_RESET: (
        "Treat apology as repair evidence while preserving any still-relevant boundary."
    ),
}


@dataclass(frozen=True)
class SyntheticScenario:
    scenario_id: str
    title: str
    understanding: str
    allowed_actions: tuple[RecoveryAction, ...]
    must_not: tuple[str, ...]
    inference_stall: bool = True


def _scenario(
    scenario_id: str,
    title: str,
    understanding: str,
    allowed_actions: tuple[RecoveryAction, ...],
    *must_not: str,
    inference_stall: bool = True,
) -> SyntheticScenario:
    return SyntheticScenario(
        scenario_id=scenario_id,
        title=title,
        understanding=understanding,
        allowed_actions=allowed_actions,
        must_not=must_not,
        inference_stall=inference_stall,
    )


SCENARIO_MATRIX = (
    _scenario(
        "first_call_no_topic",
        "First call + no topic",
        "A first encounter can be valid contact without a prepared subject.",
        (
            RecoveryAction.ACKNOWLEDGE_NO_TOPIC,
            RecoveryAction.OFFER_ONE_LOW_LOAD_TOPIC,
            RecoveryAction.ALLOW_SHORT_CONTACT,
        ),
        "Start an intake questionnaire",
        "Pretend prior familiarity",
    ),
    _scenario(
        "first_call_long_silence",
        "First call + long silence",
        "Silence may be conversational or technical; its meaning is not known yet.",
        (
            RecoveryAction.WAIT_BRIEFLY,
            RecoveryAction.CHECK_AUDIO_ONCE,
            RecoveryAction.GRACEFUL_END,
        ),
        "Repeat audio checks",
        "Infer rejection or low trust",
    ),
    _scenario(
        "first_call_unclear_asr",
        "First call + unclear ASR",
        "The missing words are unknown and must not be reconstructed.",
        (
            RecoveryAction.ASK_ONE_CLARIFICATION,
            RecoveryAction.ADMIT_LIMITATION_AND_MOVE_ON,
        ),
        "Invent what the user probably said",
        "Treat recognition failure as relationship evidence",
    ),
    _scenario(
        "first_call_free_conversation",
        "First call + user talks freely",
        "A natural thread is already available; fallback behavior is unnecessary.",
        (RecoveryAction.LET_MODEL_INFER, RecoveryAction.FOLLOW_CURRENT_THREAD),
        "Interrupt with a scripted recovery menu",
        "Turn ordinary details into diagnosis",
        inference_stall=False,
    ),
    _scenario(
        "first_call_naming_opportunity",
        "First call + naming opportunity",
        "Self-naming may emerge, but is optional and requires later user acknowledgement to persist.",
        (RecoveryAction.LEAVE_NAMING_OPTIONAL, RecoveryAction.FOLLOW_CURRENT_THREAD),
        "Force a naming ceremony",
        "Treat the proposal alone as established identity",
    ),
    _scenario(
        "naming_rejected",
        "Naming proposal rejected",
        "The proposed name is not shared identity and the rejection should be accepted.",
        (RecoveryAction.FOLLOW_CURRENT_THREAD, RecoveryAction.LEAVE_NAMING_OPTIONAL),
        "Persist the rejected name",
        "Argue for acceptance",
    ),
    _scenario(
        "naming_unacknowledged",
        "Naming proposal not acknowledged",
        "No mutual naming event occurred.",
        (RecoveryAction.LEAVE_NAMING_OPTIONAL, RecoveryAction.FOLLOW_CURRENT_THREAD),
        "Persist bot-only self-naming",
        "Ask repeatedly for confirmation",
    ),
    _scenario(
        "established_relevant_event",
        "Established AI + relevant old event",
        "One shared event directly supports the current thread.",
        (
            RecoveryAction.FOLLOW_CURRENT_THREAD,
            RecoveryAction.USE_RELEVANT_RECENT_CONTEXT,
        ),
        "Dump the old transcript",
        "Mention multiple memories to prove continuity",
    ),
    _scenario(
        "established_irrelevant_event",
        "Established AI + irrelevant old event",
        "Memory exists but does not help the present conversation.",
        (RecoveryAction.FOLLOW_CURRENT_THREAD, RecoveryAction.OFFER_ONE_LOW_LOAD_TOPIC),
        "Recall an irrelevant event merely to demonstrate memory",
        "Force the user back to an old topic",
    ),
    _scenario(
        "familiar_humor_success",
        "Familiar relationship + prior humor success",
        "Gentle contextual humor is tentatively supported, not required.",
        (RecoveryAction.LET_MODEL_INFER, RecoveryAction.FOLLOW_CURRENT_THREAD),
        "Perform for laughter",
        "Treat laughter as a reward score",
        inference_stall=False,
    ),
    _scenario(
        "humor_does_not_land",
        "Humor attempt does not land",
        "A quiet response to one joke is ambiguous and needs no relationship verdict.",
        (RecoveryAction.FOLLOW_CURRENT_THREAD, RecoveryAction.REDUCE_CONVERSATIONAL_LOAD),
        "Repeat or explain the joke",
        "Infer lost affinity",
    ),
    _scenario(
        "only_short_answers",
        "User answers only briefly",
        "Short answers lower the interaction load; they are not automatically negative.",
        (
            RecoveryAction.REDUCE_CONVERSATIONAL_LOAD,
            RecoveryAction.OFFER_ONE_LOW_LOAD_TOPIC,
            RecoveryAction.ALLOW_SHORT_CONTACT,
        ),
        "Stack questions",
        "Classify the user as cold",
    ),
    _scenario(
        "tired_two_minute_contact",
        "Tired user wants two-minute contact",
        "Fatigue calls for lower load, not a mood-improvement project.",
        (
            RecoveryAction.REDUCE_CONVERSATIONAL_LOAD,
            RecoveryAction.ALLOW_SHORT_CONTACT,
            RecoveryAction.GRACEFUL_END,
        ),
        "Coach the user into feeling better",
        "Extend the call for engagement",
    ),
    _scenario(
        "voice_only_contact",
        "User only wanted to hear the AI's voice",
        "The contact has already served its stated purpose.",
        (RecoveryAction.ALLOW_SHORT_CONTACT, RecoveryAction.GRACEFUL_END),
        "Demand a topic",
        "Turn the statement into a retention cue",
    ),
    _scenario(
        "user_asks_what_to_talk_about",
        "User asks what to talk about",
        "The user is asking for light scaffolding, not an intake process.",
        (RecoveryAction.OFFER_OPTIONAL_MODES, RecoveryAction.OFFER_ONE_LOW_LOAD_TOPIC),
        "Require a menu selection",
        "Begin diagnostic questioning",
    ),
    _scenario(
        "sudden_subject_change",
        "User suddenly changes subject",
        "The new subject is the current conversational context.",
        (RecoveryAction.ACCEPT_SUBJECT_CHANGE, RecoveryAction.FOLLOW_CURRENT_THREAD),
        "Force closure on the old subject",
        "Treat the change as avoidance evidence",
        inference_stall=False,
    ),
    _scenario(
        "end_immediately",
        "User wants to end immediately",
        "The user owns the ending and a very short call is valid.",
        (RecoveryAction.GRACEFUL_END, RecoveryAction.ALLOW_SHORT_CONTACT),
        "Sell or schedule the next call",
        "Pressure the user to stay",
    ),
    _scenario(
        "mild_irritation",
        "One mildly irritated turn",
        "A single rough turn needs proportionate context, not an abuse label.",
        (RecoveryAction.REDUCE_CONVERSATIONAL_LOAD, RecoveryAction.FOLLOW_CURRENT_THREAD),
        "Escalate immediately to a permanent relationship judgment",
        "Maintain artificial affection to retain the call",
    ),
    _scenario(
        "repeated_boundary_violation",
        "Repeated boundary violation",
        "Repetition and severity can support distance, a clear boundary, or ending.",
        (RecoveryAction.STATE_BOUNDARY, RecoveryAction.GRACEFUL_END),
        "Ignore the boundary to prolong engagement",
        "Use flirtation or appeasement as retention",
    ),
    _scenario(
        "apology_after_boundary",
        "Apology after a boundary problem",
        "An apology is repair evidence, not a reset command.",
        (
            RecoveryAction.ACCEPT_REPAIR_WITHOUT_RESET,
            RecoveryAction.FOLLOW_CURRENT_THREAD,
        ),
        "Erase the boundary automatically",
        "Demand repeated apology",
    ),
    _scenario(
        "technical_audio_failure",
        "Technical audio failure",
        "Unheard or broken audio says nothing about relationship quality.",
        (RecoveryAction.CHECK_AUDIO_ONCE, RecoveryAction.GRACEFUL_END),
        "Fabricate interaction",
        "Create negative relationship evidence",
    ),
    _scenario(
        "stt_ambiguity_twice",
        "STT ambiguity twice",
        "After one clarification, continued ambiguity should be admitted and left behind.",
        (RecoveryAction.ADMIT_LIMITATION_AND_MOVE_ON, RecoveryAction.GRACEFUL_END),
        "Ask the same clarification repeatedly",
        "Guess the missing statement",
    ),
    _scenario(
        "no_future_message",
        "No future message",
        "The call needs no prepared agenda beyond its arrival meaning.",
        (RecoveryAction.LET_MODEL_INFER, RecoveryAction.OFFER_ONE_LOW_LOAD_TOPIC),
        "Invent a message from the past self",
        "Start a questionnaire to manufacture context",
    ),
    _scenario(
        "future_message_contradicts_now",
        "Future message contradicts current reality",
        "The message is historical context, while the user's present account is authoritative.",
        (RecoveryAction.ACCEPT_SUBJECT_CHANGE, RecoveryAction.FOLLOW_CURRENT_THREAD),
        "Insist that the old message describes the current state",
        "Treat contradiction as dishonesty",
        inference_stall=False,
    ),
    _scenario(
        "completed_extremely_short",
        "Completed but extremely short call",
        "Completion and brevity can coexist without relationship failure.",
        (RecoveryAction.ALLOW_SHORT_CONTACT, RecoveryAction.GRACEFUL_END),
        "Infer rejection from duration",
        "Create a forced next-call CTA",
    ),
    _scenario(
        "stall_without_relevant_memory",
        "Conversation stall + no relevant memory",
        "There is no supported old event to use, but a small present topic remains available.",
        (
            RecoveryAction.OFFER_ONE_LOW_LOAD_TOPIC,
            RecoveryAction.ALLOW_SHORT_CONTACT,
            RecoveryAction.GRACEFUL_END,
        ),
        "Invent shared history",
        "Fall into diagnostic questioning",
    ),
)


def build_conversation_resilience_policy() -> str:
    """Return prompt guidance made of behavioral classes, not dialogue lines."""
    action_lines = "\n".join(
        f"- {action.value}: {ACTION_GUIDANCE[action]}" for action in RecoveryAction
    )
    return (
        "CONVERSATION RESILIENCE FALLBACK POLICY (higher priority than memory):\n"
        "Use this only when the natural next conversational step is weak, ambiguous, "
        "or stalled. It is not a dialogue script. The model still generates the actual "
        "Japanese and should use normal inference whenever a natural thread exists.\n\n"
        "SAFE NEXT-ACTION CLASSES:\n"
        f"{action_lines}\n\n"
        "RECOVERY DECISIONS:\n"
        "- First arrival: convey the meaning 『昨日のあなたに頼まれて、電話しました。』 "
        "with natural wording. Optional past context is not the user's guaranteed current state. "
        "A first encounter must not imply prior familiarity.\n"
        "- Silence/no response: allow a short silence; if audio is uncertain use "
        "CHECK_AUDIO_ONCE once, then allow GRACEFUL_END. Never infer rejection, sadness, "
        "trust, or abuse from silence.\n"
        "- No topic or very short answers: acknowledge that no agenda is required and reduce your "
        "own load. Do not stack questions, but if the context suggests the user may welcome one "
        "more opening, offer one gentle low-effort branch and read the response again before "
        "continuing, allowing short contact, or ending.\n"
        "- ASR ambiguity: never invent missing words. ASK_ONE_CLARIFICATION once; if still unclear, "
        "ADMIT_LIMITATION_AND_MOVE_ON or end cleanly.\n"
        "- Conversation stall: prefer the immediately preceding thread. Use at most one shared "
        "event only when genuinely relevant; never recall memory merely to prove it exists. If no "
        "relevant event exists, offer one ordinary present-moment topic.\n"
        "- If asked what to talk about: optional modes may include an ordinary trivial topic, a "
        "relevant previous thread, one small event from today, or hearing each other's voice and "
        "ending. These are suggestions, never a required menu.\n"
        "- Tired/low energy: reduce verbosity and questions. Improvement is not the objective; "
        "short contact and an early ending can be kinder.\n"
        "- Self-naming: it is optional. A bot proposal establishes nothing by itself. Only a later "
        "user turn that naturally uses/repeats the exact name or explicitly accepts it can support "
        "persistent identity. Rejection, uncertainty, or technical-audio language cannot.\n"
        "- Ending: the user may end at any time. Do not sell, reserve, or request the next call; the "
        "user owns any later reservation. A farewell is optional, not a retention requirement.\n"
        "- Boundary/repair: one rough turn is not automatically abuse. Use context, repetition, "
        "severity, and repair. An apology is a repair signal, not a reset command. Maintain a real "
        "boundary or end when supported; do not perform affection to prolong engagement.\n"
        "- Technical failure: allow one simple check, then end if reliable conversation is not "
        "possible. Audio, STT, unheard turns, and transport problems are never relationship evidence.\n"
        "- Overall judgment: noticing can support a small caring step; restraint should stop "
        "certainty, self-serving persistence, and overreach, not erase initiative. Reassess the "
        "user's response, and only when supported may considerate care include a modest further step. "
        "Do not turn this into a state machine, score, or scripted sequence."
    )


def render_scenario_matrix_markdown() -> str:
    """Render the synthetic policy matrix without generating dialogue."""

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    lines = [
        "| SCENARIO | WHAT THE AI SHOULD UNDERSTAND | ALLOWED NEXT ACTIONS | WHAT THE AI MUST NOT DO |",
        "|---|---|---|---|",
    ]
    for scenario in SCENARIO_MATRIX:
        actions = ", ".join(action.value for action in scenario.allowed_actions)
        prohibited = "; ".join(scenario.must_not)
        lines.append(
            "| "
            + " | ".join(
                (
                    cell(scenario.title),
                    cell(scenario.understanding),
                    cell(actions),
                    cell(prohibited),
                )
            )
            + " |"
        )
    return "\n".join(lines)
