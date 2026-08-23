"""Server-side synchronization for the one CALL-E Windows delivery task.

This module never dispatches a phone call or loads CALL-E credentials.  Live
mode only registers or removes the existing one-shot Windows task; the task
continues to perform delivery later through ``run_dispatch.ps1``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence
from uuid import uuid4


DELIVERY_MODES = {"disabled", "preview", "live"}
TASK_NAME = "CALL-E-Hackathon-LiveCall"
SCHEDULER_DIAGNOSTICS_SCHEMA_VERSION = 2
MAX_DIAGNOSTIC_TEXT_CHARS = 2_000
MAX_DIAGNOSTIC_LINES = 30

_OPERATIONAL_MARKER_PREFIXES = (
    "TASK_STAGE=",
    "TASK_REGISTER=",
    "TASK_REMOVE=",
    "TASK_SCHEDULER_CHANGED=",
    "ARMED=",
    "REAL_CALL_SCHEDULED=",
)
_POWERSHELL_ERROR_COMMANDS = (
    "ConvertFrom-Json",
    "Get-ScheduledTask",
    "New-ScheduledTaskAction",
    "New-ScheduledTaskTrigger",
    "Register-ScheduledTask",
    "Unregister-ScheduledTask",
)


def sanitize_scheduler_diagnostic(value: object) -> str:
    """Allowlist operational scheduler lines; omit all payload-shaped text."""
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    allowed: list[str] = []
    for source_line in text.splitlines():
        line = source_line.strip()
        if not line:
            continue
        is_marker = line.startswith(_OPERATIONAL_MARKER_PREFIXES)
        is_error_header = any(
            line.startswith(f"{command} :")
            for command in _POWERSHELL_ERROR_COMMANDS
        )
        is_error_metadata = bool(
            re.match(
                r"^(?:\+\s*)?(?:CategoryInfo|FullyQualifiedErrorId)\s*:",
                line,
                flags=re.IGNORECASE,
            )
        )
        is_location = line.startswith("At ") or line.startswith("発生場所 ")
        if not (is_marker or is_error_header or is_error_metadata or is_location):
            continue

        if is_marker:
            marker_prefix = next(
                prefix
                for prefix in _OPERATIONAL_MARKER_PREFIXES
                if line.startswith(prefix)
            )
            marker_value = line[len(marker_prefix) :]
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", marker_value):
                marker_value = "[OMITTED]"
            line = marker_prefix + marker_value
        elif is_error_header:
            command = next(
                candidate
                for candidate in _POWERSHELL_ERROR_COMMANDS
                if line.startswith(f"{candidate} :")
            )
            lowered = line.casefold()
            if command == "ConvertFrom-Json":
                detail = "JSON parsing failed."
            elif "access is denied" in lowered or "アクセスが拒否" in line:
                detail = "Access denied."
            elif "not found" in lowered or "見つかりません" in line:
                detail = "Required resource was not found."
            else:
                detail = "PowerShell command failed."
            line = f"{command}: {detail}"
        elif is_error_metadata:
            if re.match(r"^(?:\+\s*)?CategoryInfo\s*:", line, re.IGNORECASE):
                exception = re.search(
                    r"\b([A-Za-z][A-Za-z0-9.]*Exception)\b",
                    line,
                )
                line = (
                    f"CategoryInfo: {exception.group(1)}"
                    if exception
                    else "CategoryInfo: [OMITTED]"
                )
            else:
                identifier = line.split(":", 1)[-1].strip()
                if not re.fullmatch(r"[A-Za-z0-9.,_-]{1,240}", identifier):
                    identifier = "[OMITTED]"
                line = f"FullyQualifiedErrorId: {identifier}"
        elif is_location:
            line_number = re.search(r":(\d+)\b", line)
            line = (
                f"PowerShell script location: line {line_number.group(1)}"
                if line_number
                else "PowerShell script location: [OMITTED]"
            )
        line = re.sub(
            r"(?i)\b[A-Z]:\\Users\\.*?(?=:\d+\b)",
            "[REDACTED_PERSONAL_PATH]",
            line,
        )
        line = re.sub(
            r"(?i)\b[A-Z]:\\Users\\[^\s\r\n]+",
            "[REDACTED_PERSONAL_PATH]",
            line,
        )
        line = re.sub(
            r"(?i)\b(CALLE_API_KEY|CALLE_TEST_PHONE|API[_ -]?KEY|AUTHORIZATION)"
            r"\b\s*[:=]\s*\S+",
            lambda match: f"{match.group(1)}=[REDACTED]",
            line,
        )
        line = re.sub(
            r"(?i)\bBearer\s+\S+",
            "Bearer [REDACTED]",
            line,
        )
        line = re.sub(
            r"\bsk-[A-Za-z0-9_-]{8,}\b",
            "[REDACTED_API_KEY]",
            line,
        )
        line = re.sub(
            r"(?<![\w])\+?\d[\d\s().-]{7,}\d",
            "[REDACTED_PHONE]",
            line,
        )
        allowed.append(line)
        if len(allowed) >= MAX_DIAGNOSTIC_LINES:
            break

    if not allowed and text.strip():
        allowed.append("[UNSTRUCTURED_DIAGNOSTIC_OMITTED]")
    bounded = "\n".join(allowed)
    if len(bounded) > MAX_DIAGNOSTIC_TEXT_CHARS:
        bounded = bounded[:MAX_DIAGNOSTIC_TEXT_CHARS] + "...[TRUNCATED]"
    return bounded


class SchedulerCommandError(RuntimeError):
    """Safe scheduler failure whose unrestricted subprocess result is discarded."""

    def __init__(self, diagnostics: dict[str, object]) -> None:
        super().__init__("DELIVERY_SCHEDULER_COMMAND_FAILED")
        self.diagnostics = diagnostics


class DeliveryRegistrar(Protocol):
    """Minimal boundary around Task Scheduler mutation."""

    mutates_windows_task_scheduler: bool

    def replace(self, *, pending_file: Path, scheduled_for: str) -> None: ...

    def remove(self) -> None: ...


@dataclass(frozen=True)
class DeliveryResult:
    mode: str
    operation: str
    state: str
    coherent: bool
    scheduled_for: str | None = None
    error_code: str | None = None

    def public_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "operation": self.operation,
            "state": self.state,
            "coherent": self.coherent,
            "scheduled_for": self.scheduled_for,
            "error_code": self.error_code,
        }


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class WindowsTaskRegistrar:
    """Calls the validated PowerShell task registrar without loading secrets."""

    mutates_windows_task_scheduler = True

    def __init__(
        self,
        app_root: Path,
        *,
        command_runner: CommandRunner = subprocess.run,
        diagnostics_dir: Path | None = None,
    ) -> None:
        self.app_root = app_root.resolve()
        self.script = self.app_root / "register_live_task.ps1"
        self.command_runner = command_runner
        self.diagnostics_dir = (
            diagnostics_dir.resolve()
            if diagnostics_dir is not None
            else self.app_root / "diagnostics" / "results"
        )
        self.last_failure: dict[str, object] | None = None

    def _safe_failure(
        self,
        *,
        failure_stage: str,
        failure_category: str,
        exception_type: str,
        exit_code: int | None,
        success_marker: str,
        stdout: object = "",
        stderr: object = "",
    ) -> SchedulerCommandError:
        diagnostics: dict[str, object] = {
            "schema_version": SCHEDULER_DIAGNOSTICS_SCHEMA_VERSION,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "failure_stage": failure_stage,
            "failure_category": failure_category,
            "exception_type": exception_type,
            "command_basename": self.script.name,
            "task_name": TASK_NAME,
            "task_registration_state": "not_confirmed",
            "exit_code": exit_code,
            "success_marker": success_marker,
            "success_marker_observed": success_marker in str(stdout or ""),
            "sanitized_stdout": sanitize_scheduler_diagnostic(stdout),
            "sanitized_stderr": sanitize_scheduler_diagnostic(stderr),
        }
        self.last_failure = diagnostics
        try:
            self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            destination = self.diagnostics_dir / (
                f"scheduler_bridge_failure_{timestamp}_{uuid4().hex[:8]}.json"
            )
            temporary = destination.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(diagnostics, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            temporary.replace(destination)
        except OSError:
            pass
        return SchedulerCommandError(diagnostics)

    def _run(self, arguments: Sequence[str], success_marker: str) -> None:
        failure_stage = (
            "task_removal" if "-Remove" in arguments else "task_registration"
        )
        if not self.script.is_file():
            raise self._safe_failure(
                failure_stage=failure_stage,
                failure_category="registrar_script_missing",
                exception_type="FileNotFoundError",
                exit_code=None,
                success_marker=success_marker,
                stderr="Scheduler registrar script is not available.",
            )
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script),
            *arguments,
        ]
        try:
            completed = self.command_runner(
                command,
                cwd=self.app_root,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except Exception as error:
            raise self._safe_failure(
                failure_stage=failure_stage,
                failure_category="subprocess_exception",
                exception_type=type(error).__name__,
                exit_code=None,
                success_marker=success_marker,
                stdout=getattr(error, "stdout", ""),
                stderr=getattr(error, "stderr", "") or str(error),
            ) from None
        if completed.returncode != 0 or success_marker not in completed.stdout:
            category = (
                "nonzero_exit"
                if completed.returncode != 0
                else "missing_success_marker"
            )
            raise self._safe_failure(
                failure_stage=failure_stage,
                failure_category=category,
                exception_type="SchedulerCommandError",
                exit_code=completed.returncode,
                success_marker=success_marker,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )

    def replace(self, *, pending_file: Path, scheduled_for: str) -> None:
        del scheduled_for
        expected_pending = (self.app_root / "data" / "pending_call.json").resolve()
        if pending_file.resolve() != expected_pending:
            raise RuntimeError("LIVE_DELIVERY_REQUIRES_PRODUCTION_PENDING_PATH")
        self._run(["-Arm"], "TASK_REGISTER=PASS")

    def remove(self) -> None:
        self._run(["-Remove", "-Arm"], "TASK_REMOVE=PASS")


class DeliverySynchronizer:
    """Maps disabled/preview/live policy to an injectable registrar."""

    def __init__(
        self,
        mode: str = "disabled",
        registrar: DeliveryRegistrar | None = None,
    ) -> None:
        normalized = mode.strip().lower()
        if normalized not in DELIVERY_MODES:
            raise ValueError("CALL_E_DELIVERY_MODE must be disabled, preview, or live.")
        if normalized == "live" and registrar is None:
            raise ValueError("Live delivery mode requires a task registrar.")
        self.mode = normalized
        self.registrar = registrar

    @classmethod
    def from_environment(
        cls,
        *,
        app_root: Path,
        storage_mode: str,
        environment: Mapping[str, str] | None = None,
    ) -> "DeliverySynchronizer":
        env = os.environ if environment is None else environment
        mode = env.get("CALL_E_DELIVERY_MODE", "disabled").strip().lower()
        if mode not in DELIVERY_MODES:
            raise ValueError("CALL_E_DELIVERY_MODE must be disabled, preview, or live.")
        if mode == "live":
            if storage_mode != "real":
                raise ValueError(
                    "Live delivery mode is forbidden with isolated storage."
                )
            return cls(mode, WindowsTaskRegistrar(app_root))
        return cls(mode)

    @property
    def task_scheduler_mutation_enabled(self) -> bool:
        return bool(
            self.mode == "live"
            and self.registrar is not None
            and self.registrar.mutates_windows_task_scheduler
        )

    def synchronize(
        self,
        *,
        operation: str,
        pending_file: Path,
        scheduled_for: str,
    ) -> DeliveryResult:
        if self.mode == "disabled":
            return DeliveryResult(
                mode=self.mode,
                operation=operation,
                state="disabled",
                coherent=True,
                scheduled_for=scheduled_for,
            )
        if self.mode == "preview":
            return DeliveryResult(
                mode=self.mode,
                operation=operation,
                state="previewed",
                coherent=True,
                scheduled_for=scheduled_for,
            )
        try:
            assert self.registrar is not None
            self.registrar.replace(
                pending_file=pending_file,
                scheduled_for=scheduled_for,
            )
        except Exception:
            return DeliveryResult(
                mode=self.mode,
                operation=operation,
                state="indeterminate",
                coherent=False,
                scheduled_for=scheduled_for,
                error_code="DELIVERY_SCHEDULE_SYNC_FAILED",
            )
        return DeliveryResult(
            mode=self.mode,
            operation=operation,
            state="scheduled",
            coherent=True,
            scheduled_for=scheduled_for,
        )

    def remove(self, *, scheduled_for: str | None) -> DeliveryResult:
        if self.mode == "disabled":
            return DeliveryResult(
                mode=self.mode,
                operation="cancel",
                state="disabled",
                coherent=True,
                scheduled_for=scheduled_for,
            )
        if self.mode == "preview":
            return DeliveryResult(
                mode=self.mode,
                operation="cancel",
                state="previewed_removal",
                coherent=True,
                scheduled_for=scheduled_for,
            )
        try:
            assert self.registrar is not None
            self.registrar.remove()
        except Exception:
            return DeliveryResult(
                mode=self.mode,
                operation="cancel",
                state="indeterminate",
                coherent=False,
                scheduled_for=scheduled_for,
                error_code="DELIVERY_SCHEDULE_REMOVE_FAILED",
            )
        return DeliveryResult(
            mode=self.mode,
            operation="cancel",
            state="removed",
            coherent=True,
            scheduled_for=scheduled_for,
        )
