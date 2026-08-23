from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from qa_isolation import IsolatedApiClient, QA_INSTANCE_HEADER
from tests.profile_fixtures import completed_profile_store
from web_api import StorageConfig, WebServer


APP_ROOT = Path(__file__).resolve().parents[1]


def request_json(
    url: str,
    *,
    method: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=data, method=method, headers=request_headers)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class StaleHandler(BaseHTTPRequestHandler):
    post_count = 0

    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send({"ok": True, "dispatch_enabled": False})

    def do_POST(self) -> None:
        type(self).post_count += 1
        self._send({"unexpected": True})


class QAIsolationTests(unittest.TestCase):
    def test_state_counts_unique_completed_calls_without_exposing_call_log(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-call-count-") as temporary:
            root = Path(temporary)
            data_root = root / "data"
            results_root = root / "results"
            data_root.mkdir()
            results_root.mkdir()
            records = [
                {"call_id": "completed-1", "status": "completed"},
                {"call_id": "failed-1", "status": "failed"},
                {"call_id": "completed-1", "status": "completed"},
                {
                    "call_id": "completed-2",
                    "status": "completed",
                    "structured_result": {"conversation_completed": "no"},
                },
            ]
            (data_root / "completed_calls.jsonl").write_text(
                "\n".join(json.dumps(item) for item in records) + "\n",
                encoding="utf-8",
            )
            storage = StorageConfig(
                app_root=APP_ROOT,
                data_root=data_root,
                results_root=results_root,
                storage_mode="isolated",
                instance_id="call-count-test",
            )
            server = WebServer(
                ("127.0.0.1", 0),
                storage,
                profile_store=completed_profile_store(storage.data_root),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, response = request_json(
                    f"http://127.0.0.1:{server.server_port}/api/state",
                    method="GET",
                )
                self.assertEqual(status, 200)
                self.assertEqual(response["completed_call_count"], 2)
                self.assertEqual(response["history"], [])
                self.assertNotIn("completed_calls", response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_isolated_mode_rejects_real_roots(self) -> None:
        environment = {
            "CALL_E_STORAGE_MODE": "isolated",
            "CALL_E_DATA_ROOT": str(APP_ROOT / "data"),
            "CALL_E_RESULTS_ROOT": str(APP_ROOT / "results"),
            "CALL_E_INSTANCE_ID": "qa-test",
        }
        with self.assertRaises(ValueError):
            StorageConfig.from_environment(environment, app_root=APP_ROOT)

    def test_isolated_server_requires_matching_instance_header(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-web-api-") as temporary:
            root = Path(temporary)
            data_root = root / "data"
            results_root = root / "results"
            data_root.mkdir()
            results_root.mkdir()
            storage = StorageConfig.from_environment(
                {
                    "CALL_E_STORAGE_MODE": "isolated",
                    "CALL_E_DATA_ROOT": str(data_root),
                    "CALL_E_RESULTS_ROOT": str(results_root),
                    "CALL_E_INSTANCE_ID": "qa-isolated-001",
                },
                app_root=APP_ROOT,
            )
            server = WebServer(
                ("127.0.0.1", 0),
                storage,
                profile_store=completed_profile_store(storage.data_root),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            scheduled = (datetime.now().astimezone() + timedelta(hours=5)).strftime(
                "%Y-%m-%d %H:%M"
            )
            payload = {"scheduled_for": scheduled, "future_message": "synthetic only"}
            try:
                status, response = request_json(
                    base + "/api/calls",
                    method="POST",
                    payload=payload,
                )
                self.assertEqual(status, 409)
                self.assertEqual(response["code"], "STORAGE_INSTANCE_MISMATCH")
                self.assertFalse((data_root / "pending_call.json").exists())

                client = IsolatedApiClient(base, "qa-isolated-001")
                client.verify()
                status, _ = client.mutate("/api/calls", method="POST", payload=payload)
                self.assertEqual(status, 200)
                self.assertTrue((data_root / "pending_call.json").exists())

                status, _ = client.mutate("/api/calls", method="DELETE")
                self.assertEqual(status, 200)
                self.assertFalse((data_root / "pending_call.json").exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_qa_client_will_not_write_to_stale_localhost_process(self) -> None:
        StaleHandler.post_count = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), StaleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = IsolatedApiClient(
            f"http://127.0.0.1:{server.server_port}",
            "qa-current-run",
        )
        try:
            with self.assertRaises(RuntimeError):
                client.mutate(
                    "/api/calls",
                    method="POST",
                    payload={"scheduled_for": "2030-01-01 12:00"},
                )
            self.assertEqual(StaleHandler.post_count, 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_real_mode_rejects_qa_instance_header_before_booking(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-real-guard-") as temporary:
            root = Path(temporary)
            data_root = root / "data"
            results_root = root / "results"
            data_root.mkdir()
            results_root.mkdir()
            storage = StorageConfig(
                app_root=APP_ROOT,
                data_root=data_root,
                results_root=results_root,
                storage_mode="real",
                instance_id=None,
            )
            server = WebServer(
                ("127.0.0.1", 0),
                storage,
                profile_store=completed_profile_store(storage.data_root),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, response = request_json(
                    f"http://127.0.0.1:{server.server_port}/api/calls",
                    method="POST",
                    payload={"scheduled_for": "2030-01-01 12:00"},
                    headers={QA_INSTANCE_HEADER: "qa-mistake"},
                )
                self.assertEqual(status, 409)
                self.assertEqual(response["code"], "STORAGE_INSTANCE_MISMATCH")
                self.assertFalse((data_root / "pending_call.json").exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
