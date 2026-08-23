from __future__ import annotations

import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from booking_policy import (
    DEFAULT_MINIMUM_MINUTES,
    DEVELOPMENT_MINIMUM_MINUTES,
    BookingPolicy,
    effective_minimum_minutes,
)
from delivery_schedule import DeliverySynchronizer
from qa_isolation import QA_INSTANCE_HEADER
from tests.profile_fixtures import completed_profile_store
from web_api import StorageConfig, WebServer


APP_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def running_server(storage: StorageConfig, policy: BookingPolicy):
    server = WebServer(
        ("127.0.0.1", 0),
        storage,
        DeliverySynchronizer("preview"),
        policy,
        completed_profile_store(storage.data_root),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
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


class ShortHorizonPolicyTests(unittest.TestCase):
    def storage(self, root: Path, instance_id: str) -> StorageConfig:
        data_root = root / "data"
        results_root = root / "results"
        data_root.mkdir(parents=True)
        results_root.mkdir(parents=True)
        return StorageConfig.from_environment(
            {
                "CALL_E_STORAGE_MODE": "isolated",
                "CALL_E_DATA_ROOT": str(data_root),
                "CALL_E_RESULTS_ROOT": str(results_root),
                "CALL_E_INSTANCE_ID": instance_id,
            },
            app_root=APP_ROOT,
        )

    def create(
        self,
        base_url: str,
        instance_id: str,
        target: datetime,
    ) -> tuple[int, dict]:
        return request_json(
            base_url,
            "/api/calls",
            method="POST",
            payload={
                "scheduled_for": target.strftime("%Y-%m-%d %H:%M"),
                "future_message": "synthetic short-horizon test",
            },
            instance_id=instance_id,
        )

    def test_default_policy_is_four_hours_and_flag_is_off(self) -> None:
        policy = BookingPolicy.from_environment({}, bind_host="127.0.0.1")

        self.assertEqual(policy.minimum_minutes, DEFAULT_MINIMUM_MINUTES)
        self.assertFalse(policy.development_short_horizon_enabled)
        self.assertEqual(effective_minimum_minutes({}), DEFAULT_MINIMUM_MINUTES)

    def test_development_override_requires_explicit_flag_and_loopback(self) -> None:
        policy = BookingPolicy.from_environment(
            {"CALL_E_DEV_SHORT_HORIZON": "1"},
            bind_host="127.0.0.1",
        )

        self.assertEqual(policy.minimum_minutes, DEVELOPMENT_MINIMUM_MINUTES)
        self.assertTrue(policy.development_short_horizon_enabled)
        self.assertEqual(
            effective_minimum_minutes(policy.subprocess_environment({})),
            DEVELOPMENT_MINIMUM_MINUTES,
        )
        with self.assertRaises(ValueError):
            BookingPolicy.from_environment(
                {"CALL_E_DEV_SHORT_HORIZON": "1"},
                bind_host="0.0.0.0",
            )
        with self.assertRaises(ValueError):
            policy.require_compatible_bind_host("192.0.2.1")

    def test_default_rejects_under_four_hours_and_allows_over_four_hours(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-default-gate-") as temporary:
            instance_id = "default-four-hour-gate"
            storage = self.storage(Path(temporary), instance_id)
            now = datetime.now().astimezone()
            with running_server(storage, BookingPolicy()) as base_url:
                too_soon, _ = self.create(
                    base_url,
                    instance_id,
                    now + timedelta(hours=3),
                )
                allowed, response = self.create(
                    base_url,
                    instance_id,
                    now + timedelta(hours=4, minutes=2),
                )
                health_status, health = request_json(
                    base_url,
                    "/api/health",
                    instance_id=instance_id,
                )

            self.assertEqual(too_soon, 409)
            self.assertEqual(allowed, 200)
            self.assertIsNotNone(response["pending"])
            self.assertEqual(health_status, 200)
            self.assertEqual(health["booking_minimum_minutes"], 240)
            self.assertFalse(health["dev_short_horizon_enabled"])
            self.assertTrue(health["scheduler_diagnostics_loaded"])

    def test_development_mode_allows_minutes_and_preserves_one_pending_rule(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-dev-short-gate-") as temporary:
            instance_id = "development-short-gate"
            storage = self.storage(Path(temporary), instance_id)
            policy = BookingPolicy.from_environment(
                {"CALL_E_DEV_SHORT_HORIZON": "1"},
                bind_host="127.0.0.1",
            )
            now = datetime.now().astimezone()
            with running_server(storage, policy) as base_url:
                allowed, response = self.create(
                    base_url,
                    instance_id,
                    now + timedelta(minutes=7),
                )
                duplicate, _ = self.create(
                    base_url,
                    instance_id,
                    now + timedelta(minutes=9),
                )
                health_status, health = request_json(
                    base_url,
                    "/api/health",
                    instance_id=instance_id,
                )

            self.assertEqual(allowed, 200)
            self.assertEqual(response["pending"]["delivery"]["state"], "previewed")
            self.assertEqual(duplicate, 409)
            self.assertEqual(health_status, 200)
            self.assertEqual(health["booking_minimum_minutes"], 5)
            self.assertTrue(health["dev_short_horizon_enabled"])

    def test_development_mode_does_not_weaken_ten_year_maximum(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-dev-max-gate-") as temporary:
            instance_id = "development-max-gate"
            storage = self.storage(Path(temporary), instance_id)
            policy = BookingPolicy.from_environment(
                {"CALL_E_DEV_SHORT_HORIZON": "1"},
                bind_host="localhost",
            )
            now = datetime.now().astimezone()
            try:
                too_far = now.replace(year=now.year + 11)
            except ValueError:
                too_far = now.replace(year=now.year + 11, day=28)
            with running_server(storage, policy) as base_url:
                status, _ = self.create(base_url, instance_id, too_far)

            self.assertEqual(status, 409)
            self.assertFalse(storage.pending_file.exists())


if __name__ == "__main__":
    unittest.main()
