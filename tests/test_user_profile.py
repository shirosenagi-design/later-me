from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import dispatch_call
from delivery_schedule import DeliverySynchronizer
from qa_isolation import QA_INSTANCE_HEADER
from tests.profile_fixtures import (
    ReversingTestProtector,
    completed_profile_store,
    synthetic_phone,
)
from user_profile import (
    ProfileAlreadyExistsError,
    ProfileProtectionError,
    ProfileValidationError,
    UserProfileStore,
    WindowsDpapiProtector,
)
from web_api import StorageConfig, WebServer


APP_ROOT = Path(__file__).resolve().parents[1]


def request_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    instance_id: str | None = None,
) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if instance_id is not None:
        headers[QA_INSTANCE_HEADER] = instance_id
    request = Request(base + path, data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class FirstRunProfileTests(unittest.TestCase):
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

    def running_server(self, storage: StorageConfig, store: UserProfileStore):
        server = WebServer(
            ("127.0.0.1", 0),
            storage,
            DeliverySynchronizer("preview"),
            profile_store=store,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_port}"

    def test_fresh_profile_requires_both_confirmations_and_returns_no_phone(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-profile-api-") as temporary:
            instance_id = "profile-first-run-test"
            storage = self.make_storage(Path(temporary), instance_id)
            store = UserProfileStore(
                storage.profile_root,
                protector=ReversingTestProtector(),
            )
            server, thread, base = self.running_server(storage, store)
            try:
                status, fresh = request_json(base, "/api/profile")
                self.assertEqual(status, 200)
                self.assertEqual(
                    fresh,
                    {
                        "completed": False,
                        "language": None,
                        "phone_registered": False,
                    },
                )

                incomplete = {
                    "language": "en",
                    "phone": synthetic_phone(),
                    "own_number_confirmed": True,
                    "future_calls_authorized": False,
                }
                status, response = request_json(
                    base,
                    "/api/profile",
                    method="POST",
                    payload=incomplete,
                    instance_id=instance_id,
                )
                self.assertEqual(status, 400)
                self.assertEqual(response["code"], "PROFILE_VALIDATION_FAILED")
                self.assertFalse(store.profile_file.exists())

                incomplete["future_calls_authorized"] = True
                status, created = request_json(
                    base,
                    "/api/profile",
                    method="POST",
                    payload=incomplete,
                    instance_id=instance_id,
                )
                self.assertEqual(status, 201)
                self.assertEqual(created["language"], "en")
                self.assertTrue(created["completed"])
                self.assertTrue(created["phone_registered"])
                self.assertNotIn("phone", created)
                self.assertNotIn(synthetic_phone().encode(), store.profile_file.read_bytes())

                status, returning = request_json(base, "/api/profile")
                self.assertEqual(status, 200)
                self.assertEqual(returning, created)
                self.assertNotIn("api_key", json.dumps(returning).lower())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_first_run_cannot_overwrite_completed_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-profile-once-") as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            store = completed_profile_store(data_root)
            before = store.profile_file.read_bytes()
            with self.assertRaises(ProfileAlreadyExistsError):
                store.create_first_run(
                    language="en",
                    phone=synthetic_phone(),
                    own_number_confirmed=True,
                    future_calls_authorized=True,
                )
            self.assertEqual(store.profile_file.read_bytes(), before)

    def test_language_en_and_ja_persist_in_protected_temp_profiles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-profile-language-") as temporary:
            root = Path(temporary)
            for language in ("en", "ja"):
                store = completed_profile_store(root / language, language)
                profile = store.require_complete()
                self.assertEqual(profile.language, language)
                self.assertEqual(profile.phone_e164, synthetic_phone())
                self.assertNotIn(
                    synthetic_phone().encode(),
                    store.profile_file.read_bytes(),
                )

    def test_booking_is_blocked_until_profile_is_completed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-profile-guard-") as temporary:
            instance_id = "profile-booking-guard"
            storage = self.make_storage(Path(temporary), instance_id)
            store = UserProfileStore(
                storage.profile_root,
                protector=ReversingTestProtector(),
            )
            server, thread, base = self.running_server(storage, store)
            try:
                status, response = request_json(
                    base,
                    "/api/calls",
                    method="POST",
                    payload={"scheduled_for": "2030-01-01 12:00"},
                    instance_id=instance_id,
                )
                self.assertEqual(status, 428)
                self.assertEqual(response["code"], "PROFILE_REQUIRED")
                self.assertFalse(storage.pending_file.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_dispatch_destination_and_language_come_from_registered_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-profile-dispatch-") as temporary:
            store = completed_profile_store(Path(temporary) / "data", "en")
            profile = dispatch_call.resolve_registered_destination(store)
            self.assertEqual(profile.phone_e164, synthetic_phone())
            self.assertEqual(profile.language, "en")
            task = dispatch_call.build_call_task(
                profile.phone_e164,
                memory_root=Path(temporary) / "usual_ai",
                language=profile.language,
            )
            self.assertTrue(task.startswith(f"Call {synthetic_phone()}."))
            self.assertIn("Speak English calmly", task)

            dispatch_source = Path(dispatch_call.__file__).read_text(encoding="utf-8")
            self.assertNotIn('os.environ.get("CALLE_TEST_PHONE")', dispatch_source)
            runner = (APP_ROOT / "run_dispatch.ps1").read_text(encoding="utf-8-sig")
            self.assertIn("$secretLoader -ApiKeyOnly", runner)

            onboarding_source = (APP_ROOT / "web" / "src" / "Onboarding.tsx").read_text(
                encoding="utf-8"
            ).lower()
            self.assertNotIn("calle_api_key", onboarding_source)
            self.assertNotIn("api key", onboarding_source)

    def test_invalid_phone_or_language_never_creates_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-profile-invalid-") as temporary:
            store = UserProfileStore(
                Path(temporary) / "profile",
                protector=ReversingTestProtector(),
            )
            with self.assertRaises(ProfileValidationError):
                store.create_first_run(
                    language="fr",
                    phone="not-a-number",
                    own_number_confirmed=True,
                    future_calls_authorized=True,
                )
            self.assertFalse(store.profile_file.exists())

    def test_dpapi_adapter_passes_plaintext_only_through_stdin(self) -> None:
        plaintext = synthetic_phone().encode("utf-8")
        completed = SimpleNamespace(
            returncode=0,
            stdout=b"SYNTHETIC_PROTECTED",
            stderr=b"",
        )
        protector = WindowsDpapiProtector(executable="powershell.exe")
        with patch("user_profile.subprocess.run", return_value=completed) as run:
            self.assertEqual(protector.protect(plaintext), b"SYNTHETIC_PROTECTED")
        arguments = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertNotIn(synthetic_phone(), " ".join(arguments))
        self.assertNotEqual(options["input"], plaintext)
        self.assertEqual(base64.b64decode(options["input"]), plaintext)
        self.assertNotIn("env", options)
        self.assertTrue(options["capture_output"])
        self.assertIn("ProtectedData]::Protect", arguments[-1])
        self.assertIn("DataProtectionScope]::CurrentUser", arguments[-1])
        self.assertNotIn("ConvertFrom-SecureString", arguments[-1])

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is Windows-only")
    def test_windows_dpapi_round_trip_uses_only_temporary_storage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="calle-profile-dpapi-") as temporary:
            protector = WindowsDpapiProtector()
            plaintext = "CALL-E synthetic DPAPI / 日本語".encode("utf-8")
            try:
                protected = protector.protect(plaintext)
            except ProfileProtectionError:
                self.skipTest("DPAPI is unavailable in this process token")
            self.assertNotEqual(protected, plaintext)
            self.assertEqual(protector.unprotect(protected), plaintext)

            for language in ("en", "ja"):
                store = UserProfileStore(
                    Path(temporary) / language / "profile",
                    protector=protector,
                )
                store.create_first_run(
                    language=language,
                    phone=synthetic_phone(),
                    own_number_confirmed=True,
                    future_calls_authorized=True,
                )
                loaded = store.require_complete()
                self.assertEqual(loaded.language, language)
                self.assertEqual(loaded.phone_e164, synthetic_phone())
                self.assertNotIn(
                    synthetic_phone().encode(),
                    store.profile_file.read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
