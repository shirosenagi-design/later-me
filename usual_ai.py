"""Persistent identity, shared history, and relationship hypotheses for CALL-E.

This module never places a call. It consumes an already-saved call result and
stores only concise evidence-derived memory, not complete transcripts.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

BASE_PERSONA = (
    "Warm but not ingratiating; reliable; slightly unusual; able to hold "
    "boundaries; does not constantly praise; does not try to maximize call "
    "duration. Silence and having nothing to discuss are valid conversation."
)

DEFAULT_DIMENSIONS = {
    "conversational_distance": {
        "hypothesis": "first_encounter",
        "confidence": "unknown",
        "evidence_event_ids": [],
    },
    "humor_style": {
        "hypothesis": "unknown",
        "confidence": "unknown",
        "evidence_event_ids": [],
    },
    "preferred_interaction_style": {
        "hypothesis": "unknown",
        "confidence": "unknown",
        "evidence_event_ids": [],
    },
    "comfortable_with_short_contact": {
        "hypothesis": "unknown",
        "confidence": "unknown",
        "evidence_event_ids": [],
    },
    "boundary_state": {
        "hypothesis": "no_explicit_boundary_observed",
        "confidence": "unknown",
        "evidence_event_ids": [],
    },
    "repair_state": {
        "hypothesis": "no_repair_needed_observed",
        "confidence": "unknown",
        "evidence_event_ids": [],
    },
}

NAME_PATTERN = re.compile(
    r"(?:私|わたし|僕|ぼく)の名前は[\s、,:：]*[「『\"]?"
    r"([ぁ-んァ-ヶ一-龯々A-Za-z0-9・_-]{1,20})",
    re.IGNORECASE,
)
NAME_ACCEPTANCE_PATTERNS = (
    re.compile(r"その名前(?:で|が)?(?:いい|好き|素敵)(?:だね|ですね|です|だ|ね|よ)?"),
    re.compile(r"その名前(?:、|は)?(?:覚えた|覚えました|了解|わかった|分かった)"),
    re.compile(r"(?:そう|それで)(?:呼ぶ|呼びます)(?:ね|よ)?"),
)
NAME_REJECTION_OR_UNCLEAR_MARKERS = (
    "嫌",
    "いや",
    "やめ",
    "呼ばない",
    "別の",
    "違う",
    "変えて",
    "だめ",
    "ダメ",
    "微妙",
    "聞こえない",
    "聞き取れない",
    "途切れ",
    "音が",
    "もう一度",
    "何て",
    "なんて",
    "わからない",
    "分からない",
)
ADDRESS_PATTERN = re.compile(
    r"(?:私|わたし|僕|ぼく)のことは[\s、]*"
    r"([ぁ-んァ-ヶ一-龯々A-Za-z0-9・_-]{1,20})"
    r"(?:って|と)呼んで"
)
LAUGHTER_PATTERN = re.compile(r"笑った|笑っちゃ|ふふ|はは|あは|ｗ|w{2,}", re.IGNORECASE)
PERSONAL_MARKERS = (
    "今日",
    "昨日",
    "今朝",
    "帰り道",
    "仕事",
    "学校",
    "家族",
    "友だち",
    "友達",
    "見つけた",
    "行った",
    "会った",
)
BOUNDARY_MARKERS = ("聞かないで", "触れないで", "やめて", "その話はしたくない")
REPAIR_MARKERS = ("ごめん", "すみません", "わかった", "もう聞かない")
SHORT_CONTACT_MARKERS = (
    "今日は短く",
    "少しだけ",
    "もう切る",
    "そろそろ切る",
    "話すことない",
    "話すことはない",
    "特にない",
    "何もない",
)
TOPIC_TAGS = {
    "散歩": ("散歩", "帰り道", "歩いた"),
    "食べもの": ("パン", "料理", "ごはん", "食べ", "店"),
    "仕事": ("仕事", "職場"),
    "学校": ("学校", "授業"),
    "家族": ("家族", "母", "父", "兄", "姉", "弟", "妹"),
    "友人": ("友だち", "友達", "友人"),
}

TECHNICAL_FAILURE_STATUSES = {"failed", "dispatch_failed", "technical_failure"}
TECHNICAL_DELIVERY_OUTCOMES = {
    "dispatch_indeterminate",
    "terminal_delivery_failed",
    "terminal_result_missing_call_id",
    "completed_transcript_unavailable",
}


def _normalized_text(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _event_id(
    call_id: str,
    event_type: str,
    turn_indices: list[int],
    summary: str,
) -> str:
    raw = f"{call_id}:{event_type}:{','.join(map(str, turn_indices))}:{summary}"
    return "evt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _event(
    call_id: str,
    occurred_at: str,
    event_type: str,
    summary: str,
    turn_indices: list[int],
    *,
    tags: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": _event_id(call_id, event_type, turn_indices, summary),
        "call_id": call_id,
        "occurred_at": occurred_at,
        "event_type": event_type,
        "summary": _normalized_text(summary, 180),
        "evidence": {
            "source": "saved_transcript",
            "turn_indices": turn_indices,
        },
        "tags": tags or [],
        "attributes": attributes or {},
    }


def _topic_tags(text: str) -> list[str]:
    return [tag for tag, markers in TOPIC_TAGS.items() if any(marker in text for marker in markers)]


def _origin_story_summary(text: str) -> str:
    if "水面" in text and "時間" in text:
        return "時間のあいだに残る水面のイメージから、AI自身が選んだ名前。"
    return "最初の通話で、AI自身が会話の流れから選んだ名前。"


def _shared_event_summary(tags: list[str]) -> str:
    if tags:
        return f"ユーザーは{'・'.join(tags)}に関する日常の出来事を共有した。"
    return "ユーザーは、その日の身近な出来事をひとつ共有した。"


def _speaker(turn: dict[str, Any]) -> str:
    value = str(turn.get("speaker") or "").strip().lower()
    if value in {"bot", "assistant", "ai"}:
        return "bot"
    if value in {"user", "human", "recipient"}:
        return "user"
    return value


def _valid_transcript(result: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = result.get("transcript")
    if not isinstance(transcript, list):
        raise ValueError("Saved result transcript must be a list.")
    valid: list[dict[str, Any]] = []
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        speaker = _speaker(turn)
        text = _normalized_text(turn.get("text"), 1000)
        if speaker in {"bot", "user"} and text:
            valid.append({"speaker": speaker, "text": text})
    return valid


def _is_technical_failure(result: dict[str, Any]) -> bool:
    status = _normalized_text(result.get("status"), 80).lower()
    delivery_outcome = _normalized_text(
        result.get("delivery_outcome"),
        120,
    ).lower()
    transcript_retrieval = result.get("transcript_retrieval")
    transcript_unavailable = bool(
        isinstance(transcript_retrieval, dict)
        and str(transcript_retrieval.get("status") or "").lower() == "failed"
    )
    return bool(
        result.get("technical_failure") is True
        or status in TECHNICAL_FAILURE_STATUSES
        or delivery_outcome in TECHNICAL_DELIVERY_OUTCOMES
        or transcript_unavailable
    )


def _user_establishes_ai_name(text: str, chosen_name: str) -> bool:
    """Return true only for conservative, affirmative user-side naming evidence."""
    if any(marker in text for marker in NAME_REJECTION_OR_UNCLEAR_MARKERS):
        return False

    escaped_name = re.escape(chosen_name)
    name_used_as_phrase = re.search(
        rf"(?:^|[\s、。！!？?「『]){escaped_name}(?:$|[\s、。！!？?」』])",
        text,
        re.IGNORECASE,
    )
    if name_used_as_phrase:
        return True

    return any(pattern.search(text) for pattern in NAME_ACCEPTANCE_PATTERNS)


def _extract_identity(
    transcript: list[dict[str, Any]],
    call_id: str,
    occurred_at: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for index, turn in enumerate(transcript):
        if turn["speaker"] != "bot":
            continue
        match = NAME_PATTERN.search(turn["text"])
        if not match:
            continue
        chosen_name = match.group(1).strip("「『\"』」.,。")
        acknowledgement_index = next(
            (
                later_index
                for later_index in range(index + 1, len(transcript))
                if transcript[later_index]["speaker"] == "user"
                and _user_establishes_ai_name(
                    transcript[later_index]["text"], chosen_name
                )
            ),
            None,
        )
        if acknowledgement_index is None:
            continue
        identity = {
            "schema_version": SCHEMA_VERSION,
            "chosen_name": chosen_name,
            "origin_story": _origin_story_summary(turn["text"]),
            "first_call_id": call_id,
            "created_at": occurred_at,
        }
        identity_event = _event(
            call_id,
            occurred_at,
            "ai_self_naming",
            f"AIが初対面で「{chosen_name}」という名前を選び、ユーザーとの会話の中で共有された。",
            [index, acknowledgement_index],
            attributes={
                "chosen_name": chosen_name,
                "establishment_evidence": "bot_proposal_then_user_acknowledgement",
            },
        )
        return identity, identity_event
    return None, None


def _extract_events(
    transcript: list[dict[str, Any]],
    call_id: str,
    occurred_at: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for index, turn in enumerate(transcript):
        if turn["speaker"] != "user":
            continue
        text = turn["text"]
        if len(text) >= 8 and any(marker in text for marker in PERSONAL_MARKERS):
            tags = _topic_tags(text)
            events.append(
                _event(
                    call_id,
                    occurred_at,
                    "shared_conversation",
                    _shared_event_summary(tags),
                    [index],
                    tags=tags,
                )
            )
            break

    for index, turn in enumerate(transcript):
        if turn["speaker"] != "user" or not LAUGHTER_PATTERN.search(turn["text"]):
            continue
        previous = next(
            (
                prior
                for prior in range(index - 1, max(-1, index - 4), -1)
                if transcript[prior]["speaker"] == "bot"
            ),
            None,
        )
        if previous is not None:
            events.append(
                _event(
                    call_id,
                    occurred_at,
                    "successful_humor",
                    "軽い状況的なユーモアに、ユーザーが笑いで応じた。",
                    [previous, index],
                    attributes={"humor_style": "gentle_contextual"},
                )
            )
            break

    for index, turn in enumerate(transcript):
        if turn["speaker"] != "user":
            continue
        match = ADDRESS_PATTERN.search(turn["text"])
        if match:
            events.append(
                _event(
                    call_id,
                    occurred_at,
                    "form_of_address",
                    f"ユーザーは「{match.group(1)}」と呼ばれることを希望した。",
                    [index],
                    attributes={"form_of_address": match.group(1)},
                )
            )
            break

    for index, turn in enumerate(transcript):
        if turn["speaker"] != "user" or not any(marker in turn["text"] for marker in SHORT_CONTACT_MARKERS):
            continue
        events.append(
            _event(
                call_id,
                occurred_at,
                "short_contact_accepted",
                "話題がないことや短い接触の希望が、会話としてそのまま受け止められた。",
                [index],
            )
        )
        break

    for index, turn in enumerate(transcript):
        if turn["speaker"] != "user" or not any(marker in turn["text"] for marker in BOUNDARY_MARKERS):
            continue
        boundary = _event(
            call_id,
            occurred_at,
            "boundary",
            "ユーザーが会話上の明確な境界を示した。",
            [index],
        )
        events.append(boundary)
        repair_index = next(
            (
                later
                for later in range(index + 1, min(len(transcript), index + 4))
                if transcript[later]["speaker"] == "bot"
                and any(marker in transcript[later]["text"] for marker in REPAIR_MARKERS)
            ),
            None,
        )
        if repair_index is not None:
            events.append(
                _event(
                    call_id,
                    occurred_at,
                    "repair",
                    "AIが境界を認め、同じ話題を押さないと応答した。",
                    [index, repair_index],
                )
            )
        break

    return events


def _new_relationship_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "last_call_id": None,
        "dimensions": json.loads(json.dumps(DEFAULT_DIMENSIONS)),
    }


def _set_dimension(
    state: dict[str, Any],
    name: str,
    hypothesis: str,
    confidence: str,
    event_ids: list[str],
) -> None:
    current = state["dimensions"][name]
    combined = list(dict.fromkeys([*current.get("evidence_event_ids", []), *event_ids]))
    state["dimensions"][name] = {
        "hypothesis": hypothesis,
        "confidence": confidence,
        "evidence_event_ids": combined[-8:],
    }


def _update_relationship_state(
    state: dict[str, Any],
    events: list[dict[str, Any]],
    call_id: str,
    occurred_at: str,
) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_type.setdefault(event["event_type"], []).append(event)

    shared = by_type.get("shared_conversation", [])
    humor = by_type.get("successful_humor", [])
    recurring = by_type.get("recurring_topic", [])
    short = by_type.get("short_contact_accepted", [])
    boundary = by_type.get("boundary", [])
    repair = by_type.get("repair", [])

    if shared:
        _set_dimension(
            state,
            "conversational_distance",
            "gently_familiar",
            "low",
            [event["event_id"] for event in shared],
        )
        _set_dimension(
            state,
            "preferred_interaction_style",
            "responds_to_specific_everyday_details",
            "low",
            [event["event_id"] for event in shared],
        )
    if recurring:
        _set_dimension(
            state,
            "conversational_distance",
            "established_shared_reference",
            "medium",
            [event["event_id"] for event in recurring],
        )
    if humor:
        _set_dimension(
            state,
            "humor_style",
            "gentle_contextual_humor_may_be_welcome",
            "low",
            [event["event_id"] for event in humor],
        )
    if short:
        _set_dimension(
            state,
            "comfortable_with_short_contact",
            "explicitly_accepts_brief_or_topicless_contact",
            "medium",
            [event["event_id"] for event in short],
        )
    if boundary:
        _set_dimension(
            state,
            "boundary_state",
            "explicit_boundary_must_be_respected",
            "high",
            [event["event_id"] for event in boundary],
        )
    if repair:
        _set_dimension(
            state,
            "repair_state",
            "repair_acknowledged_do_not_reopen_unprompted",
            "medium",
            [event["event_id"] for event in repair],
        )

    state["updated_at"] = occurred_at
    state["last_call_id"] = call_id
    return state


@dataclass(frozen=True)
class MemoryPaths:
    root: Path

    @property
    def identity(self) -> Path:
        return self.root / "ai_identity.json"

    @property
    def history(self) -> Path:
        return self.root / "shared_history.jsonl"

    @property
    def relationship(self) -> Path:
        return self.root / "relationship_state.json"

    @property
    def processed_calls(self) -> Path:
        return self.root / "processed_calls.json"


class UsualAIStore:
    def __init__(self, root: Path | str):
        self.paths = MemoryPaths(Path(root).resolve())

    def load_identity(self) -> dict[str, Any] | None:
        return _read_json(self.paths.identity, None)

    def load_history(self) -> list[dict[str, Any]]:
        if not self.paths.history.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.paths.history.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def load_relationship_state(self) -> dict[str, Any]:
        return _read_json(self.paths.relationship, _new_relationship_state())

    def _write_history(self, events: list[dict[str, Any]]) -> None:
        self.paths.history.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.history.with_suffix(".jsonl.tmp")
        content = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.paths.history)

    def _add_recurring_topics(
        self,
        existing: list[dict[str, Any]],
        new_events: list[dict[str, Any]],
        call_id: str,
        occurred_at: str,
    ) -> None:
        shared = [
            event
            for event in [*existing, *new_events]
            if event.get("event_type") == "shared_conversation"
        ]
        existing_recurring = {
            tag
            for event in existing
            if event.get("event_type") == "recurring_topic"
            for tag in event.get("tags", [])
        }
        for tag in TOPIC_TAGS:
            supporting_calls = {
                event.get("call_id") for event in shared if tag in event.get("tags", [])
            }
            if len(supporting_calls) >= 2 and tag not in existing_recurring:
                new_events.append(
                    _event(
                        call_id,
                        occurred_at,
                        "recurring_topic",
                        f"「{tag}」は、複数の通話で自然に戻ってきた共有話題。",
                        [],
                        tags=[tag],
                    )
                )

    def process_result(self, result: dict[str, Any]) -> dict[str, Any]:
        call_id = _normalized_text(result.get("call_id"), 120)
        if not call_id:
            raise ValueError("Saved result must contain call_id.")
        occurred_at = _normalized_text(
            result.get("completed_at_local")
            or result.get("completed_at")
            or result.get("created_at")
        )
        if not occurred_at:
            raise ValueError("Saved result must contain a completion timestamp.")
        transcript = _valid_transcript(result)
        digest_source = json.dumps(
            {"call_id": call_id, "transcript": transcript},
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
        processed = _read_json(
            self.paths.processed_calls,
            {"schema_version": SCHEMA_VERSION, "calls": {}},
        )
        previous = processed["calls"].get(call_id)
        if previous:
            if previous.get("source_digest") != digest:
                raise ValueError("A different artifact already used this call_id.")
            return {
                "status": "already_processed",
                "call_id": call_id,
                "new_event_ids": [],
            }

        existing_history = self.load_history()
        existing_ids = {event["event_id"] for event in existing_history}
        technical_failure = _is_technical_failure(result)
        identity_to_write = None
        new_events: list[dict[str, Any]] = []
        if not technical_failure:
            new_identity, identity_event = _extract_identity(
                transcript,
                call_id,
                occurred_at,
            )
            current_identity = self.load_identity()
            new_events = _extract_events(transcript, call_id, occurred_at)
            if (
                current_identity is None
                and new_identity is not None
                and identity_event is not None
            ):
                identity_to_write = new_identity
                new_events.insert(0, identity_event)

            self._add_recurring_topics(
                existing_history,
                new_events,
                call_id,
                occurred_at,
            )
            new_events = [
                event for event in new_events if event["event_id"] not in existing_ids
            ]
            relationship = _update_relationship_state(
                self.load_relationship_state(),
                new_events,
                call_id,
                occurred_at,
            )

            self._write_history([*existing_history, *new_events])
            _atomic_write_json(self.paths.relationship, relationship)
            if identity_to_write is not None:
                _atomic_write_json(self.paths.identity, identity_to_write)
        processed["calls"][call_id] = {
            "source_digest": digest,
            "processed_at": occurred_at,
            "event_ids": [event["event_id"] for event in new_events],
        }
        _atomic_write_json(self.paths.processed_calls, processed)
        return {
            "status": "processed",
            "call_id": call_id,
            "new_event_ids": [event["event_id"] for event in new_events],
        }

    def process_result_file(self, result_path: Path | str) -> dict[str, Any]:
        payload = json.loads(Path(result_path).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("Saved result must be a JSON object.")
        return self.process_result(payload)

    def generate_next_call_context(self, future_message: str | None = None) -> str:
        identity = self.load_identity()
        history = self.load_history()
        relationship = self.load_relationship_state()
        dimensions = relationship["dimensions"]

        important_types = {
            "boundary": 0,
            "repair": 1,
            "form_of_address": 2,
            "recurring_topic": 3,
            "shared_conversation": 4,
            "successful_humor": 5,
            "short_contact_accepted": 6,
        }
        relevant = [event for event in history if event.get("event_type") in important_types]
        relevant.sort(
            key=lambda event: (
                important_types[event["event_type"]],
                event.get("occurred_at", ""),
            )
        )
        relevant = relevant[:6]

        lines = [
            "PERSISTENT USUAL AI CONTEXT",
            "Base persona:",
            f"- {BASE_PERSONA}",
            "- Conversation comes first: do not administer a questionnaire or diagnose the user.",
            "AI identity:",
        ]
        if identity:
            lines.extend(
                [
                    f"- Your self-chosen name is {identity['chosen_name']}.",
                    f"- Name origin from the first call: {identity['origin_story']}",
                    "- This name is shared history, not a user-configurable setting.",
                ]
            )
        else:
            lines.extend(
                [
                    "- No self-chosen name has been established yet.",
                    "- Do not ask the user to configure a name; a name may emerge naturally in a first encounter.",
                ]
            )

        lines.append("Relevant shared history (use only when natural):")
        if relevant:
            lines.extend(f"- {event['summary']}" for event in relevant)
        else:
            lines.append("- No shared events are established yet; do not invent familiarity.")

        lines.append("Tentative relationship hypotheses and behavioral implications:")
        distance = dimensions["conversational_distance"]["hypothesis"]
        if distance == "first_encounter":
            lines.append("- Treat this as a first encounter; do not imply prior familiarity.")
        else:
            lines.append(
                "- Use a lightly familiar tone. Keep explanations slightly shorter than on a first encounter, while checking ambiguity."
            )

        humor = dimensions["humor_style"]["hypothesis"]
        if humor == "gentle_contextual_humor_may_be_welcome":
            lines.append(
                "- A small gentle, contextual joke landed once. Similar light humor may be used when it arises naturally; do not force it."
            )
        else:
            lines.append("- Do not assume shared humor yet.")

        preferred = dimensions["preferred_interaction_style"]["hypothesis"]
        if preferred == "responds_to_specific_everyday_details":
            lines.append(
                "- Respond to concrete everyday details without turning them into a lesson, praise, or a questionnaire."
            )

        short = dimensions["comfortable_with_short_contact"]["hypothesis"]
        if short == "explicitly_accepts_brief_or_topicless_contact":
            lines.append(
                "- Brief or topicless contact has been explicitly comfortable before; allow it without trying to extend the call."
            )
        else:
            lines.append("- Let silence or 'nothing to talk about' stand without trying to lengthen the call.")

        if dimensions["boundary_state"]["hypothesis"] == "explicit_boundary_must_be_respected":
            lines.append("- An explicit boundary exists in shared history; do not reopen it unprompted.")
        if dimensions["repair_state"]["hypothesis"] == "repair_acknowledged_do_not_reopen_unprompted":
            lines.append("- A prior repair was acknowledged; preserve it through behavior rather than repeated apology.")

        message = _normalized_text(future_message, 500)
        if message:
            lines.extend(
                [
                    "Optional context left by the user's past self:",
                    f"- {message}",
                    "- Use this only if relevant; do not treat it as a mandatory topic.",
                ]
            )
        lines.append("Never mention files, scores, confidence values, or the memory system to the user.")
        return "\n".join(lines)
