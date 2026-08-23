"""Hard isolation checks for localhost QA and test storage.

An isolated client verifies the server instance before every mutation. This
prevents a stale real-data localhost server from receiving a test write.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


QA_INSTANCE_HEADER = "X-CALL-E-QA-Instance"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def require_isolated_storage_roots(
    data_root: Path | str,
    results_root: Path | str,
    *,
    app_root: Path | str,
) -> tuple[Path, Path]:
    app = Path(app_root).resolve()
    data = Path(data_root).resolve()
    results = Path(results_root).resolve()
    real_data = (app / "data").resolve()
    real_results = (app / "results").resolve()

    if data.name != "data":
        raise ValueError("Isolated data root must be a directory named 'data'.")
    if data == results or _is_within(data, results) or _is_within(results, data):
        raise ValueError("Isolated data and result roots must be separate.")
    if _is_within(data, real_data) or _is_within(results, real_results):
        raise ValueError("Isolated mode cannot use the real data or results root.")
    return data, results


def require_isolated_memory_root(
    memory_root: Path | str,
    *,
    app_root: Path | str,
) -> Path:
    app = Path(app_root).resolve()
    root = Path(memory_root).resolve()
    if _is_within(root, (app / "data").resolve()) or _is_within(
        root, (app / "results").resolve()
    ):
        raise ValueError("Test memory cannot be stored under real data or results.")
    return root


def validate_isolated_health(payload: Any, expected_instance_id: str) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("Local API health response is not an object.")
    if payload.get("storage_mode") != "isolated":
        raise RuntimeError("Local API is not an isolated test instance.")
    if payload.get("instance_id") != expected_instance_id:
        raise RuntimeError("Local API instance identity does not match this test run.")
    if payload.get("dispatch_enabled") is not False:
        raise RuntimeError("Local API does not explicitly report dispatch disabled.")


class IsolatedApiClient:
    """Small QA client that refuses to mutate an unverified localhost API."""

    def __init__(self, base_url: str, instance_id: str, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.instance_id = instance_id
        self.timeout = timeout

    def _json_request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        qa_header: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if qa_header:
            headers[QA_INSTANCE_HEADER] = self.instance_id
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = json.loads(error.read().decode("utf-8"))
            return error.code, body

    def verify(self) -> dict[str, Any]:
        status, health = self._json_request("/api/health")
        if status != 200:
            raise RuntimeError("Local API health check failed.")
        validate_isolated_health(health, self.instance_id)
        return health

    def mutate(
        self,
        path: str,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        self.verify()
        return self._json_request(
            path,
            method=method,
            payload=payload,
            qa_header=True,
        )
