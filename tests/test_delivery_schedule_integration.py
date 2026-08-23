from __future__ import annotations

import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import dispatch_call
from delivery_schedule import (
    MAX_DIAGNOSTIC_TEXT_CHARS,
    DeliverySynchronizer,
    SchedulerCommandError,
    WindowsTaskRegistrar,
    sanitize_scheduler_diagnostic,
)
from qa_isolation import QA_INSTANCE_HEADER
from tests.profile_fixtures import completed_profile_store
from web_api import StorageConfig, WebServer


APP_ROOT = Path(__file__).resolve().parents[1]


def request_json(
    base_url: str,
    path: str,
    *,
    method: str,
    payload: dict | None = None,
    instance_id: str,
) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            QA_INSTANCE_HEADER: instance_id,
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class FakeRegistrar:
    mutates_windows_task_scheduler = False

    def __init__(
        self,
        *,
        fail_replace: bool = False,
        fail_remove: bool = False,
    ) -> None:
        self.fail_replace = fail_replace
        self.fail_remove = fail_remove
        self.replace_calls: list[str] = []
        self.remove_calls = 0
        self.active_schedules: set[str] = set()

    def replace(self, *, pending_file: Path, scheduled_for: str) -> None:
        self.replace_calls.append(scheduled_for)
        if self.fail_replace:
            raise RuntimeError("synthetic scheduling failure")
        self.active_schedules.clear()
        self.active_schedules.add(scheduled_for)
        self.last_pending_file = pending_file

    def remove(self) -> None:
        self.remove_calls += 1
        if self.fail_remove:
            raise RuntimeError("synthetic removal failure")
        self.active_schedules.clear()


class MutationCapableFakeRegistrar(FakeRegistrar):
    mutates_windows_task_scheduler = True


@contextmanager
def running_server(
    storage: StorageConfig,
    delivery: DeliverySynchronizer,
):
    server = WebServer(
        ("127.0.0.1", 0),
        storage,
        delivery,
        profile_store=completed_profile_store(storage.data_root),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class BrowserDeliveryIntegrationTests(unittest.TestCase):
    def make_storage(self, root: Path, instance_id: str) -> StorageConfig:
        data_root = root / "data"
        results_root = root / "results"
        data_root.mkdir()
        results_root.mkdir()
        return StorageConfig.from_environment(
            {
                "CALL_E_STORAGE_MODE": "isolated",
                "CALL_E_DATA_ROOT": str(data_root),
                "CALL_E_RESULTS_ROOT": str(results_root),
                "CALL_E_INSTANCE_ID": instance_id,
            },
            app_root=APP_ROOT,
        )

    def target(self, hours_ahead: int) -> str:
        return (
            datetime.now().astimezone() + timedelta(hours=hours_ahead)
        ).strftime("%Y-%m-%d %H:%M")

    def create(
        self,
        base: str,
        instance_id: str,
        scheduled_for: str,
    ) -> tuple[int, dict]:
        return request_json(
            base,
            "/api/calls",
            method="POST",
            payload={
                "scheduled_for": scheduled_for,
                "future_message": "synthetic browser booking",
            },
            instance_id=instance_id,
        )

    def test_default_disabled_create_never_calls_registrar(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-disabled-") as temporary:
            instance_id = "delivery-disabled-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar()
            delivery = DeliverySynchronizer("disabled", registrar)
            with running_server(storage, delivery) as base:
                status, response = self.create(base, instance_id, self.target(5))

            self.assertEqual(status, 200)
            self.assertEqual(response["delivery"]["state"], "disabled")
            self.assertEqual(registrar.replace_calls, [])
            self.assertEqual(registrar.remove_calls, 0)

    def test_environment_default_is_disabled_and_preview_is_non_mutating(self) -> None:
        default = DeliverySynchronizer.from_environment(
            app_root=APP_ROOT,
            storage_mode="real",
            environment={},
        )
        preview = DeliverySynchronizer.from_environment(
            app_root=APP_ROOT,
            storage_mode="isolated",
            environment={"CALL_E_DELIVERY_MODE": "preview"},
        )

        self.assertEqual(default.mode, "disabled")
        self.assertFalse(default.task_scheduler_mutation_enabled)
        result = preview.synchronize(
            operation="create",
            pending_file=Path("synthetic") / "data" / "pending_call.json",
            scheduled_for="2030-01-01T12:00:00+09:00",
        )
        self.assertEqual(result.state, "previewed")
        self.assertTrue(result.coherent)
        self.assertFalse(preview.task_scheduler_mutation_enabled)

    def test_environment_live_mode_is_forbidden_with_isolated_storage(self) -> None:
        with self.assertRaises(ValueError):
            DeliverySynchronizer.from_environment(
                app_root=APP_ROOT,
                storage_mode="isolated",
                environment={"CALL_E_DELIVERY_MODE": "live"},
            )

    def test_live_create_requests_exactly_one_future_registration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-create-") as temporary:
            instance_id = "delivery-create-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar()
            delivery = DeliverySynchronizer("live", registrar)
            target = self.target(5)
            with running_server(storage, delivery) as base:
                status, response = self.create(base, instance_id, target)

            self.assertEqual(status, 200)
            persisted_target = response["pending"]["scheduled_for"]
            self.assertEqual(
                datetime.fromisoformat(persisted_target).strftime("%Y-%m-%d %H:%M"),
                target,
            )
            self.assertEqual(registrar.replace_calls, [persisted_target])
            self.assertEqual(registrar.active_schedules, {persisted_target})
            self.assertEqual(response["pending"]["delivery"]["state"], "scheduled")

    def test_live_change_replaces_old_schedule_with_only_new_time(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-change-") as temporary:
            instance_id = "delivery-change-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar()
            delivery = DeliverySynchronizer("live", registrar)
            old_target = self.target(5)
            new_target = self.target(7)
            with running_server(storage, delivery) as base:
                create_status, create_response = self.create(
                    base,
                    instance_id,
                    old_target,
                )
                self.assertEqual(create_status, 200)
                persisted_old_target = create_response["pending"]["scheduled_for"]
                status, response = request_json(
                    base,
                    "/api/calls/change",
                    method="POST",
                    payload={"scheduled_for": new_target},
                    instance_id=instance_id,
                )

            self.assertEqual(status, 200)
            persisted_new_target = response["pending"]["scheduled_for"]
            self.assertEqual(
                datetime.fromisoformat(persisted_new_target).strftime("%Y-%m-%d %H:%M"),
                new_target,
            )
            self.assertEqual(
                registrar.replace_calls,
                [persisted_old_target, persisted_new_target],
            )
            self.assertEqual(registrar.active_schedules, {persisted_new_target})
            self.assertNotIn(persisted_old_target, registrar.active_schedules)

    def test_live_cancel_removes_matching_schedule_and_pending(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-cancel-") as temporary:
            instance_id = "delivery-cancel-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar()
            delivery = DeliverySynchronizer("live", registrar)
            with running_server(storage, delivery) as base:
                self.assertEqual(self.create(base, instance_id, self.target(5))[0], 200)
                status, response = request_json(
                    base,
                    "/api/calls",
                    method="DELETE",
                    instance_id=instance_id,
                )

            self.assertEqual(status, 200)
            self.assertEqual(registrar.remove_calls, 1)
            self.assertEqual(registrar.active_schedules, set())
            self.assertIsNone(response["pending"])
            self.assertFalse(storage.pending_file.exists())

    def test_scheduler_failure_is_indeterminate_and_not_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-failure-") as temporary:
            instance_id = "delivery-failure-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar(fail_replace=True)
            delivery = DeliverySynchronizer("live", registrar)
            target = self.target(5)
            with running_server(storage, delivery) as base:
                status, response = self.create(base, instance_id, target)
                state_status, state = request_json(
                    base,
                    "/api/state",
                    method="GET",
                    instance_id=instance_id,
                )

            self.assertEqual(status, 503)
            self.assertFalse(response["delivery"]["coherent"])
            self.assertEqual(response["pending"]["delivery"]["state"], "indeterminate")
            self.assertEqual(
                response["delivery"]["error_code"],
                "DELIVERY_SCHEDULE_SYNC_FAILED",
            )
            self.assertNotIn("stderr", json.dumps(response))
            self.assertNotIn("stdout", json.dumps(response))
            self.assertIsNotNone(response["error"])
            self.assertEqual(state_status, 200)
            self.assertEqual(state["pending"]["delivery"]["state"], "indeterminate")
            self.assertEqual(len(registrar.replace_calls), 1)
            self.assertEqual(
                datetime.fromisoformat(registrar.replace_calls[0]).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                target,
            )

    def test_cancel_removal_failure_keeps_pending_and_reports_indeterminate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-remove-failure-") as temporary:
            instance_id = "delivery-remove-failure-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar()
            delivery = DeliverySynchronizer("live", registrar)
            with running_server(storage, delivery) as base:
                self.assertEqual(self.create(base, instance_id, self.target(5))[0], 200)
                registrar.fail_remove = True
                status, response = request_json(
                    base,
                    "/api/calls",
                    method="DELETE",
                    instance_id=instance_id,
                )

            self.assertEqual(status, 503)
            self.assertTrue(storage.pending_file.exists())
            self.assertEqual(response["pending"]["delivery"]["state"], "indeterminate")
            self.assertEqual(len(registrar.active_schedules), 1)

    def test_windows_registrar_command_shape_uses_existing_one_shot_script(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-registrar-shape-") as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            (root / "register_live_task.ps1").write_text(
                "# synthetic registrar boundary",
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def fake_runner(arguments, **_kwargs):
                calls.append(list(arguments))
                marker = (
                    "TASK_REMOVE=PASS"
                    if "-Remove" in arguments
                    else "TASK_REGISTER=PASS"
                )
                return type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": marker, "stderr": ""},
                )()

            registrar = WindowsTaskRegistrar(
                root,
                command_runner=fake_runner,
                diagnostics_dir=root / "diagnostics",
            )
            registrar.replace(
                pending_file=root / "data" / "pending_call.json",
                scheduled_for="2030-01-01T12:00:00+09:00",
            )
            registrar.remove()

            self.assertEqual(len(calls), 2)
            self.assertIn("register_live_task.ps1", calls[0][5])
            self.assertEqual(calls[0][-1], "-Arm")
            self.assertEqual(calls[1][-2:], ["-Remove", "-Arm"])
            self.assertNotIn("--execute-call", calls[0])
            self.assertNotIn("--execute-call", calls[1])
            self.assertEqual(list((root / "diagnostics").glob("*.json")), [])

    def test_nonzero_scheduler_exit_captures_only_sanitized_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-registrar-nonzero-") as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            (root / "register_live_task.ps1").write_text(
                "# synthetic registrar boundary",
                encoding="utf-8",
            )
            calls = 0

            def fake_runner(_arguments, **_kwargs):
                nonlocal calls
                calls += 1
                return type(
                    "Completed",
                    (),
                    {
                        "returncode": 17,
                        "stdout": (
                            "TASK_STAGE=REGISTER\nTASK_REGISTER=PASS\n"
                            "CALLE_API_KEY=SYNTHETIC_SECRET_VALUE\n"
                            "future_message=synthetic private note"
                        ),
                        "stderr": (
                            "ConvertFrom-Json : invalid JSON object (177): {\n"
                            '  "future_message": "秘密の日本語メッセージ",\n'
                            '  "phone": "<SYNTHETIC_TEST_PHONE>",\n'
                            '  "token": "sk-SYNTHETICSECRET123",\n'
                            '  "transcript": ["private conversation"]\n'
                            "}\n"
                            "At C:\\Users\\owner\\private-project\\"
                            "register_live_task.ps1:55 char:5\n"
                            "+ CategoryInfo : NotSpecified: (:) "
                            "[ConvertFrom-Json], ArgumentException\n"
                            "+ FullyQualifiedErrorId : System.ArgumentException,"
                            "Microsoft.PowerShell.Commands.ConvertFromJsonCommand"
                        ),
                    },
                )()

            registrar = WindowsTaskRegistrar(
                root,
                command_runner=fake_runner,
                diagnostics_dir=root / "diagnostics",
            )
            with self.assertRaises(SchedulerCommandError):
                registrar.replace(
                    pending_file=root / "data" / "pending_call.json",
                    scheduled_for="2030-01-01T12:00:00+09:00",
                )

            artifacts = list((root / "diagnostics").glob("*.json"))
            self.assertEqual(calls, 1)
            self.assertEqual(len(artifacts), 1)
            diagnostics = json.loads(artifacts[0].read_text(encoding="utf-8"))
            serialized = json.dumps(diagnostics, ensure_ascii=False)
            self.assertEqual(diagnostics["failure_stage"], "task_registration")
            self.assertEqual(diagnostics["failure_category"], "nonzero_exit")
            self.assertEqual(diagnostics["exit_code"], 17)
            self.assertTrue(diagnostics["success_marker_observed"])
            self.assertEqual(diagnostics["task_registration_state"], "not_confirmed")
            self.assertNotIn("SYNTHETIC_SECRET_VALUE", serialized)
            self.assertNotIn("SYNTHETIC_TEST_PHONE", serialized)
            self.assertNotIn("SYNTHETICSECRET123", serialized)
            self.assertNotIn("synthetic private note", serialized)
            self.assertNotIn("秘密の日本語メッセージ", serialized)
            self.assertNotIn("private conversation", serialized)
            self.assertNotIn("future_message", serialized)
            self.assertNotIn("transcript", serialized)
            self.assertNotIn(r"C:\Users\owner", serialized)
            self.assertIn("ConvertFrom-Json: JSON parsing failed.", serialized)
            self.assertIn("PowerShell script location: line 55", serialized)

    def test_unstructured_diagnostic_payload_is_omitted_and_bounded(self) -> None:
        private = (
            '{"future_message":"秘密",'
            '"transcript":"private",'
            '"phone":"<SYNTHETIC_TEST_PHONE>",'
            '"token":"sk-SYNTHETICSECRET123"}'
            + ("user-entered-text" * 1_000)
        )

        sanitized = sanitize_scheduler_diagnostic(private)

        self.assertEqual(sanitized, "[UNSTRUCTURED_DIAGNOSTIC_OMITTED]")
        self.assertLessEqual(len(sanitized), MAX_DIAGNOSTIC_TEXT_CHARS)
        self.assertNotIn("秘密", sanitized)
        self.assertNotIn("SYNTHETIC_TEST_PHONE", sanitized)
        self.assertNotIn("SYNTHETICSECRET123", sanitized)

    def test_zero_exit_without_pass_marker_is_diagnostic_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-registrar-marker-") as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            (root / "register_live_task.ps1").write_text(
                "# synthetic registrar boundary",
                encoding="utf-8",
            )
            calls = 0

            def fake_runner(_arguments, **_kwargs):
                nonlocal calls
                calls += 1
                return type(
                    "Completed",
                    (),
                    {
                        "returncode": 0,
                        "stdout": "TASK_STAGE=REGISTER",
                        "stderr": "",
                    },
                )()

            registrar = WindowsTaskRegistrar(
                root,
                command_runner=fake_runner,
                diagnostics_dir=root / "diagnostics",
            )
            with self.assertRaises(SchedulerCommandError):
                registrar.replace(
                    pending_file=root / "data" / "pending_call.json",
                    scheduled_for="2030-01-01T12:00:00+09:00",
                )

            artifacts = list((root / "diagnostics").glob("*.json"))
            self.assertEqual(calls, 1)
            self.assertEqual(len(artifacts), 1)
            diagnostics = json.loads(artifacts[0].read_text(encoding="utf-8"))
            self.assertEqual(
                diagnostics["failure_category"],
                "missing_success_marker",
            )
            self.assertEqual(diagnostics["exit_code"], 0)
            self.assertFalse(diagnostics["success_marker_observed"])

    def test_isolated_server_rejects_mutation_capable_registrar(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-guard-") as temporary:
            storage = self.make_storage(Path(temporary), "delivery-guard-test")
            registrar = MutationCapableFakeRegistrar()
            delivery = DeliverySynchronizer("live", registrar)

            with self.assertRaises(ValueError):
                WebServer(("127.0.0.1", 0), storage, delivery)

            self.assertEqual(registrar.replace_calls, [])
            self.assertEqual(registrar.remove_calls, 0)

    def test_booking_endpoints_never_instantiate_call_e_client(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-no-client-") as temporary:
            instance_id = "delivery-no-client-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar()
            delivery = DeliverySynchronizer("live", registrar)
            with (
                patch.object(
                    dispatch_call,
                    "CalleClient",
                    side_effect=AssertionError("real CALL-E client instantiated"),
                ) as client,
                running_server(storage, delivery) as base,
            ):
                self.assertEqual(self.create(base, instance_id, self.target(5))[0], 200)
                self.assertEqual(
                    request_json(
                        base,
                        "/api/calls",
                        method="DELETE",
                        instance_id=instance_id,
                    )[0],
                    200,
                )

            client.assert_not_called()

    def test_canonical_time_limits_and_one_slot_remain_authoritative(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-delivery-rules-") as temporary:
            instance_id = "delivery-rules-test"
            storage = self.make_storage(Path(temporary), instance_id)
            registrar = FakeRegistrar()
            delivery = DeliverySynchronizer("live", registrar)
            now = datetime.now().astimezone()
            try:
                too_far_date = now.replace(year=now.year + 11)
            except ValueError:
                too_far_date = now.replace(year=now.year + 11, day=28)
            too_far = too_far_date.strftime("%Y-%m-%d %H:%M")
            with running_server(storage, delivery) as base:
                self.assertEqual(self.create(base, instance_id, self.target(3))[0], 409)
                self.assertEqual(self.create(base, instance_id, too_far)[0], 409)
                self.assertEqual(self.create(base, instance_id, self.target(5))[0], 200)
                self.assertEqual(self.create(base, instance_id, self.target(6))[0], 409)

            self.assertEqual(len(registrar.replace_calls), 1)


if __name__ == "__main__":
    unittest.main()
