"""Local, non-dispatching HTTP bridge for the CALL-E web UI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from booking_policy import BookingPolicy
from delivery_schedule import (
    SCHEDULER_DIAGNOSTICS_SCHEMA_VERSION,
    DeliveryResult,
    DeliverySynchronizer,
)
from qa_isolation import QA_INSTANCE_HEADER, require_isolated_storage_roots
from relationship_trace import RelationshipTraceStore
from user_profile import (
    ProfileAlreadyExistsError,
    ProfileError,
    ProfileValidationError,
    UserProfileStore,
)


APP_ROOT = Path(__file__).resolve().parent
BOOKING_LOCK = threading.Lock()
PROFILE_LOCK = threading.Lock()
MAX_BODY_BYTES = 16_384


@dataclass(frozen=True)
class StorageConfig:
    app_root: Path
    data_root: Path
    results_root: Path
    storage_mode: str
    instance_id: str | None

    @property
    def pending_file(self) -> Path:
        return self.data_root / "pending_call.json"

    @property
    def completed_file(self) -> Path:
        return self.data_root / "completed_calls.jsonl"

    @property
    def booking_cwd(self) -> Path:
        return self.data_root.parent

    @property
    def profile_root(self) -> Path:
        return self.data_root / "profile"

    @property
    def relationship_trace_root(self) -> Path:
        return self.data_root / "relationship_trace"

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        app_root: Path = APP_ROOT,
    ) -> "StorageConfig":
        env = os.environ if environment is None else environment
        app = app_root.resolve()
        mode = env.get("CALL_E_STORAGE_MODE", "real").strip().lower()
        if mode not in {"real", "isolated"}:
            raise ValueError("CALL_E_STORAGE_MODE must be 'real' or 'isolated'.")

        if mode == "real":
            if env.get("CALL_E_DATA_ROOT") or env.get("CALL_E_RESULTS_ROOT"):
                raise ValueError("Root overrides require isolated storage mode.")
            return cls(
                app_root=app,
                data_root=app / "data",
                results_root=app / "results",
                storage_mode="real",
                instance_id=None,
            )

        data_value = env.get("CALL_E_DATA_ROOT")
        results_value = env.get("CALL_E_RESULTS_ROOT")
        instance_id = env.get("CALL_E_INSTANCE_ID", "").strip()
        if not data_value or not results_value or not instance_id:
            raise ValueError(
                "Isolated mode requires CALL_E_DATA_ROOT, CALL_E_RESULTS_ROOT, "
                "and CALL_E_INSTANCE_ID."
            )
        data_root, results_root = require_isolated_storage_roots(
            data_value,
            results_value,
            app_root=app,
        )
        return cls(
            app_root=app,
            data_root=data_root,
            results_root=results_root,
            storage_mode="isolated",
            instance_id=instance_id,
        )


def public_pending(storage: StorageConfig) -> dict | None:
    if not storage.pending_file.exists():
        return None
    record = json.loads(storage.pending_file.read_text(encoding="utf-8-sig"))
    return {
        key: record.get(key)
        for key in (
            "status",
            "scheduled_for",
            "created_at",
            "updated_at",
            "future_message",
            "delivery",
        )
    }


def load_pending_record(storage: StorageConfig) -> dict | None:
    if not storage.pending_file.exists():
        return None
    value = json.loads(storage.pending_file.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Pending reservation is not an object.")
    return value


def save_pending_record(storage: StorageConfig, record: dict) -> None:
    temporary = storage.pending_file.with_suffix(".json.delivery-sync-tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(storage.pending_file)


def mark_pending_delivery(
    storage: StorageConfig,
    result: DeliveryResult,
) -> dict:
    record = load_pending_record(storage)
    if record is None:
        raise RuntimeError("Pending reservation disappeared during delivery sync.")
    record["delivery"] = {
        **result.public_payload(),
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    save_pending_record(storage, record)
    return record


def public_history(storage: StorageConfig) -> list[dict]:
    """Return only AI-chosen visible traces, never the exhaustive call ledger."""
    return RelationshipTraceStore(storage.relationship_trace_root).public_items()


def completed_call_count(storage: StorageConfig) -> int:
    """Count unique completed calls without exposing the internal call ledger."""
    if not storage.completed_file.exists():
        return 0
    call_ids: set[str] = set()
    with storage.completed_file.open("r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            try:
                result = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(result, dict) or result.get("status") != "completed":
                continue
            call_id = str(result.get("call_id") or "").strip()
            if call_id:
                call_ids.add(call_id)
    return len(call_ids)


def run_booking_script(
    storage: StorageConfig,
    script: str,
    answers: list[str],
    booking_policy: BookingPolicy | None = None,
) -> tuple[bool, str]:
    policy = booking_policy or BookingPolicy()
    completed = subprocess.run(
        [sys.executable, str(storage.app_root / script)],
        cwd=storage.booking_cwd,
        input="\n".join(answers) + "\n",
        text=True,
        capture_output=True,
        env=policy.subprocess_environment(),
        timeout=10,
        check=False,
    )
    output = completed.stdout
    pass_markers = (
        "LOCAL_RESERVATION=PASS",
        "LOCAL_CHANGE=PASS",
        "LOCAL_CANCEL=PASS",
    )
    if completed.returncode == 0 and any(marker in output for marker in pass_markers):
        return True, ""
    too_soon_message = (
        f"この開発ライブ確認では、電話は今から{policy.minimum_minutes}分以上先に置いてください。"
        if policy.development_short_horizon_enabled
        else "電話は今から4時間以上先に置いてください。"
    )
    messages = {
        "PENDING_CALL_EXISTS": "すでに未来の電話が一本あります。",
        "TOO_SOON": too_soon_message,
        "TOO_FAR": "電話を置けるのは10年先までです。",
        "INVALID_DATETIME_FORMAT": "日付と時刻を確認してください。",
        "NO_PENDING_CALL": "変更できる予約はありません。",
    }
    for marker, message in messages.items():
        if marker in output:
            return False, message
    return False, "予約を保存できませんでした。もう一度お試しください。"


class WebServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        storage: StorageConfig,
        delivery: DeliverySynchronizer | None = None,
        booking_policy: BookingPolicy | None = None,
        profile_store: UserProfileStore | None = None,
    ):
        policy = booking_policy or BookingPolicy()
        policy.require_compatible_bind_host(address[0])
        super().__init__(address, Handler)
        self.storage = storage
        self.delivery = delivery or DeliverySynchronizer()
        self.booking_policy = policy
        self.profile_store = profile_store or UserProfileStore(storage.profile_root)
        if (
            storage.storage_mode == "isolated"
            and self.delivery.task_scheduler_mutation_enabled
        ):
            self.server_close()
            raise ValueError(
                "Isolated storage cannot use a real Task Scheduler registrar."
            )


class Handler(BaseHTTPRequestHandler):
    server_version = "CALLELocal/1.1"

    @property
    def storage(self) -> StorageConfig:
        return self.server.storage  # type: ignore[attr-defined]

    @property
    def delivery(self) -> DeliverySynchronizer:
        return self.server.delivery  # type: ignore[attr-defined]

    @property
    def booking_policy(self) -> BookingPolicy:
        return self.server.booking_policy  # type: ignore[attr-defined]

    @property
    def profile_store(self) -> UserProfileStore:
        return self.server.profile_store  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("invalid body")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("invalid body")
        return value

    def mutation_is_authorized(self) -> bool:
        qa_instance = self.headers.get(QA_INSTANCE_HEADER)
        if self.storage.storage_mode == "isolated":
            return bool(qa_instance) and qa_instance == self.storage.instance_id
        return qa_instance is None

    def reject_unsafe_mutation(self) -> None:
        self.send_json(
            409,
            {
                "error": "This write does not match the local API storage instance.",
                "code": "STORAGE_INSTANCE_MISMATCH",
            },
        )

    def synchronize_pending_delivery(
        self,
        operation: str,
    ) -> tuple[DeliveryResult, str | None]:
        pending = load_pending_record(self.storage)
        if pending is None or not isinstance(pending.get("scheduled_for"), str):
            return (
                DeliveryResult(
                    mode=self.delivery.mode,
                    operation=operation,
                    state="indeterminate",
                    coherent=False,
                    error_code="PENDING_RESERVATION_MISSING_DURING_SYNC",
                ),
                "予約は保存されましたが、配信予定との同期を確認できませんでした。",
            )

        scheduled_for = pending["scheduled_for"]
        synchronizing = DeliveryResult(
            mode=self.delivery.mode,
            operation=operation,
            state="synchronizing",
            coherent=False,
            scheduled_for=scheduled_for,
        )
        try:
            mark_pending_delivery(self.storage, synchronizing)
        except (OSError, ValueError, RuntimeError):
            return (
                DeliveryResult(
                    mode=self.delivery.mode,
                    operation=operation,
                    state="indeterminate",
                    coherent=False,
                    scheduled_for=scheduled_for,
                    error_code="DELIVERY_STATE_PREPARE_FAILED",
                ),
                "予約は保存されましたが、配信同期を開始できませんでした。",
            )

        result = self.delivery.synchronize(
            operation=operation,
            pending_file=self.storage.pending_file,
            scheduled_for=scheduled_for,
        )
        try:
            mark_pending_delivery(self.storage, result)
        except (OSError, ValueError, RuntimeError):
            return (
                DeliveryResult(
                    mode=self.delivery.mode,
                    operation=operation,
                    state="indeterminate",
                    coherent=False,
                    scheduled_for=scheduled_for,
                    error_code="DELIVERY_STATE_FINALIZE_FAILED",
                ),
                "配信予定の同期結果を保存できませんでした。状態の確認が必要です。",
            )
        if not result.coherent:
            return result, "配信予定との同期を確認できませんでした。状態の確認が必要です。"
        return result, None

    def remove_pending_delivery_before_cancel(
        self,
    ) -> tuple[DeliveryResult | None, str | None]:
        pending = load_pending_record(self.storage)
        if pending is None:
            return None, None
        scheduled_for = pending.get("scheduled_for")
        if not isinstance(scheduled_for, str):
            scheduled_for = None
        synchronizing = DeliveryResult(
            mode=self.delivery.mode,
            operation="cancel",
            state="synchronizing",
            coherent=False,
            scheduled_for=scheduled_for,
        )
        try:
            mark_pending_delivery(self.storage, synchronizing)
        except (OSError, ValueError, RuntimeError):
            return (
                DeliveryResult(
                    mode=self.delivery.mode,
                    operation="cancel",
                    state="indeterminate",
                    coherent=False,
                    scheduled_for=scheduled_for,
                    error_code="DELIVERY_CANCEL_PREPARE_FAILED",
                ),
                "キャンセル前の配信状態を保存できませんでした。予約は残っています。",
            )

        result = self.delivery.remove(scheduled_for=scheduled_for)
        try:
            mark_pending_delivery(self.storage, result)
        except (OSError, ValueError, RuntimeError):
            return (
                DeliveryResult(
                    mode=self.delivery.mode,
                    operation="cancel",
                    state="indeterminate",
                    coherent=False,
                    scheduled_for=scheduled_for,
                    error_code="DELIVERY_CANCEL_FINALIZE_FAILED",
                ),
                "配信予定の解除結果を保存できませんでした。予約は残っています。",
            )
        if not result.coherent:
            return result, "配信予定を解除できたか確認できません。予約は残っています。"
        return result, None

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self.send_json(
                200,
                {
                    "pending": public_pending(self.storage),
                    "history": public_history(self.storage),
                    "completed_call_count": completed_call_count(self.storage),
                },
            )
        elif path == "/api/profile":
            try:
                profile = self.profile_store.public_status()
            except ProfileError:
                self.send_json(
                    503,
                    {
                        "error": "The protected user profile could not be read.",
                        "code": "PROFILE_UNAVAILABLE",
                    },
                )
                return
            self.send_json(200, profile)
        elif path == "/api/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "dispatch_enabled": False,
                    "delivery_mode": self.delivery.mode,
                    "task_scheduler_mutation_enabled": (
                        self.delivery.task_scheduler_mutation_enabled
                    ),
                    "storage_mode": self.storage.storage_mode,
                    "instance_id": self.storage.instance_id,
                    "booking_minimum_minutes": self.booking_policy.minimum_minutes,
                    "dev_short_horizon_enabled": (
                        self.booking_policy.development_short_horizon_enabled
                    ),
                    "scheduler_diagnostics_loaded": (
                        SCHEDULER_DIAGNOSTICS_SCHEMA_VERSION >= 2
                    ),
                },
            )
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/profile":
            self.create_first_run_profile()
            return
        if path not in ("/api/calls", "/api/calls/change"):
            self.send_json(404, {"error": "Not found"})
            return
        if not self.mutation_is_authorized():
            self.reject_unsafe_mutation()
            return
        try:
            profile_complete = bool(
                self.profile_store.public_status().get("completed")
            )
        except ProfileError:
            self.send_json(
                503,
                {
                    "error": "The protected user profile could not be read.",
                    "code": "PROFILE_UNAVAILABLE",
                },
            )
            return
        if not profile_complete:
            self.send_json(
                428,
                {
                    "error": "Complete first-run phone registration before booking.",
                    "code": "PROFILE_REQUIRED",
                },
            )
            return
        try:
            payload = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "入力を確認してください。"})
            return
        scheduled_for = payload.get("scheduled_for")
        if not isinstance(scheduled_for, str):
            self.send_json(400, {"error": "日付と時刻を確認してください。"})
            return
        delivery_result: DeliveryResult | None = None
        with BOOKING_LOCK:
            if path == "/api/calls":
                message = payload.get("future_message")
                if message is not None and not isinstance(message, str):
                    self.send_json(400, {"error": "メッセージを確認してください。"})
                    return
                ok, error = run_booking_script(
                    self.storage,
                    "create_future_call.py",
                    [scheduled_for, (message or "").strip()[:500]],
                    self.booking_policy,
                )
            else:
                ok, error = run_booking_script(
                    self.storage,
                    "manage_future_call.py",
                    ["2", scheduled_for],
                    self.booking_policy,
                )
            if ok:
                delivery_result, delivery_error = self.synchronize_pending_delivery(
                    "create" if path == "/api/calls" else "change"
                )
                if delivery_error:
                    error = delivery_error
                    ok = False
        self.send_json(
            200 if ok else (503 if delivery_result is not None else 409),
            {
                "pending": public_pending(self.storage),
                "delivery": (
                    delivery_result.public_payload()
                    if delivery_result is not None
                    else None
                ),
                "error": error or None,
            },
        )

    def create_first_run_profile(self) -> None:
        if not self.mutation_is_authorized():
            self.reject_unsafe_mutation()
            return
        try:
            payload = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Check the onboarding details."})
            return
        try:
            with PROFILE_LOCK:
                profile = self.profile_store.create_first_run(
                    language=payload.get("language"),
                    phone=payload.get("phone"),
                    own_number_confirmed=payload.get("own_number_confirmed"),
                    future_calls_authorized=payload.get(
                        "future_calls_authorized"
                    ),
                )
        except ProfileAlreadyExistsError:
            self.send_json(
                409,
                {
                    "error": "A completed user profile already exists.",
                    "code": "PROFILE_ALREADY_EXISTS",
                },
            )
            return
        except ProfileValidationError as exc:
            self.send_json(
                400,
                {
                    "error": str(exc),
                    "code": "PROFILE_VALIDATION_FAILED",
                },
            )
            return
        except (OSError, ProfileError):
            self.send_json(
                503,
                {
                    "error": "The protected user profile could not be saved.",
                    "code": "PROFILE_SAVE_FAILED",
                },
            )
            return
        self.send_json(201, profile.public_status())

    def do_DELETE(self) -> None:
        if urlparse(self.path).path != "/api/calls":
            self.send_json(404, {"error": "Not found"})
            return
        if not self.mutation_is_authorized():
            self.reject_unsafe_mutation()
            return
        delivery_result: DeliveryResult | None = None
        with BOOKING_LOCK:
            delivery_result, delivery_error = (
                self.remove_pending_delivery_before_cancel()
            )
            if delivery_error:
                ok, error = False, delivery_error
            else:
                ok, error = run_booking_script(
                    self.storage,
                    "manage_future_call.py",
                    ["3"],
                    self.booking_policy,
                )
                if not ok and delivery_result is not None:
                    indeterminate = DeliveryResult(
                        mode=self.delivery.mode,
                        operation="cancel",
                        state="indeterminate",
                        coherent=False,
                        scheduled_for=delivery_result.scheduled_for,
                        error_code="BOOKING_CANCEL_FAILED_AFTER_DELIVERY_REMOVAL",
                    )
                    try:
                        mark_pending_delivery(self.storage, indeterminate)
                    except (OSError, ValueError, RuntimeError):
                        pass
                    delivery_result = indeterminate
                    error = (
                        "配信予定は解除されましたが、予約のキャンセルを保存できませんでした。"
                    )
        self.send_json(
            200 if ok else (503 if delivery_result is not None else 409),
            {
                "pending": public_pending(self.storage),
                "delivery": (
                    delivery_result.public_payload()
                    if delivery_result is not None
                    else None
                ),
                "error": error or None,
            },
        )


def main() -> None:
    bind_host = "127.0.0.1"
    storage = StorageConfig.from_environment()
    delivery = DeliverySynchronizer.from_environment(
        app_root=storage.app_root,
        storage_mode=storage.storage_mode,
    )
    booking_policy = BookingPolicy.from_environment(bind_host=bind_host)
    port = int(os.environ.get("CALL_E_WEB_PORT", "8787"))
    server = WebServer(
        (bind_host, port),
        storage,
        delivery,
        booking_policy,
        UserProfileStore(storage.profile_root),
    )
    print(f"CALL-E local web bridge: http://{bind_host}:{port}")
    print("Storage mode:", storage.storage_mode)
    print("Delivery mode:", delivery.mode)
    print(
        "Development short-horizon:",
        (
            f"ENABLED (minimum {booking_policy.minimum_minutes} minutes)"
            if booking_policy.development_short_horizon_enabled
            else "DISABLED (canonical 4-hour minimum)"
        ),
    )
    print(
        "Scheduler diagnostics:",
        f"LOADED (schema {SCHEDULER_DIAGNOSTICS_SCHEMA_VERSION})",
    )
    print("Immediate dispatch is not exposed by this server.")
    server.serve_forever()


if __name__ == "__main__":
    main()
