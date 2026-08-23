"""Protected, local first-run profile for the single CALL-E user.

The browser can learn only whether onboarding is complete and which language
was selected.  The user's phone number is encrypted with Windows DPAPI and is
resolved only by the server-side dispatch process.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


PROFILE_SCHEMA_VERSION = 1
PROFILE_FILENAME = "user_profile.dpapi"
SUPPORTED_LANGUAGES = {"en", "ja"}
_PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
_PHONE_FORMATTING = re.compile(r"[\s().-]+")


class ProfileError(RuntimeError):
    """Base error for unavailable or invalid protected profiles."""


class ProfileValidationError(ProfileError):
    """Raised when first-run input does not satisfy the product rules."""


class ProfileAlreadyExistsError(ProfileError):
    """Raised when first-run creation would overwrite an existing profile."""


class ProfileProtectionError(ProfileError):
    """Raised when protected storage cannot be encrypted or decrypted."""


class DataProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, protected: bytes) -> bytes: ...


class WindowsDpapiProtector:
    """Current-user DPAPI through the Windows .NET implementation.

    Plaintext is supplied only through an anonymous stdin pipe.  It never
    appears in a command line, environment variable, console, or log.
    """

    _DPAPI_SETUP = (
        "$ErrorActionPreference = 'Stop';"
        "[void][Reflection.Assembly]::Load("
        "'System.Security, Version=4.0.0.0, Culture=neutral, "
        "PublicKeyToken=b03f5f7f11d50a3a');"
    )
    _PROTECT_SCRIPT = (
        _DPAPI_SETUP
        + "$encoded = [Console]::In.ReadToEnd().Trim();"
        "$plain = [Convert]::FromBase64String($encoded);"
        "$protected = [System.Security.Cryptography.ProtectedData]::Protect("
        "$plain, $null, "
        "[System.Security.Cryptography.DataProtectionScope]::CurrentUser);"
        "[Console]::Out.Write([Convert]::ToBase64String($protected));"
    )
    _UNPROTECT_SCRIPT = (
        _DPAPI_SETUP
        + "$encoded = [Console]::In.ReadToEnd().Trim();"
        "$protected = [Convert]::FromBase64String($encoded);"
        "$plain = [System.Security.Cryptography.ProtectedData]::Unprotect("
        "$protected, $null, "
        "[System.Security.Cryptography.DataProtectionScope]::CurrentUser);"
        "[Console]::Out.Write([Convert]::ToBase64String($plain));"
    )

    def __init__(self, executable: str | None = None) -> None:
        if os.name != "nt":
            raise ProfileProtectionError("Windows DPAPI is required.")
        self.executable = executable or shutil.which("powershell.exe")
        if not self.executable:
            raise ProfileProtectionError("Windows PowerShell is required.")

    def _run(self, script: str, value: bytes) -> bytes:
        try:
            completed = subprocess.run(
                [
                    self.executable,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                input=value,
                capture_output=True,
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProfileProtectionError("Windows DPAPI operation failed.") from exc
        if completed.returncode != 0 or completed.stderr or not completed.stdout:
            raise ProfileProtectionError("Windows DPAPI operation failed.")
        return completed.stdout

    def protect(self, plaintext: bytes) -> bytes:
        return self._run(
            self._PROTECT_SCRIPT,
            base64.b64encode(plaintext),
        ).strip()

    def unprotect(self, protected: bytes) -> bytes:
        encoded = self._run(self._UNPROTECT_SCRIPT, protected).strip()
        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProfileProtectionError("Windows DPAPI operation failed.") from exc


def normalize_phone(value: object) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError("A phone number is required.")
    normalized = _PHONE_FORMATTING.sub("", value.strip())
    if not _PHONE_PATTERN.fullmatch(normalized):
        raise ProfileValidationError(
            "Use an international phone number beginning with + and country code."
        )
    return normalized


@dataclass(frozen=True)
class UserProfile:
    language: str
    phone_e164: str
    own_number_confirmed: bool
    future_calls_authorized: bool
    created_at: str

    @property
    def completed(self) -> bool:
        return bool(
            self.language in SUPPORTED_LANGUAGES
            and self.phone_e164
            and self.own_number_confirmed
            and self.future_calls_authorized
        )

    def public_status(self) -> dict[str, object]:
        return {
            "completed": self.completed,
            "language": self.language if self.completed else None,
            "phone_registered": bool(self.completed),
        }


class UserProfileStore:
    def __init__(
        self,
        root: Path,
        protector: DataProtector | None = None,
    ) -> None:
        self.root = Path(root)
        self.profile_file = self.root / PROFILE_FILENAME
        self._protector = protector

    @property
    def protector(self) -> DataProtector:
        if self._protector is None:
            self._protector = WindowsDpapiProtector()
        return self._protector

    def load(self) -> UserProfile | None:
        if not self.profile_file.exists():
            return None
        try:
            plaintext = self.protector.unprotect(self.profile_file.read_bytes())
            value = json.loads(plaintext.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ProfileError) as exc:
            raise ProfileProtectionError("Protected user profile is unreadable.") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ProfileProtectionError("Protected user profile schema is invalid.")
        try:
            profile = UserProfile(
                language=str(value["language"]),
                phone_e164=normalize_phone(value["phone_e164"]),
                own_number_confirmed=value["own_number_confirmed"] is True,
                future_calls_authorized=value["future_calls_authorized"] is True,
                created_at=str(value["created_at"]),
            )
        except (KeyError, ProfileValidationError) as exc:
            raise ProfileProtectionError("Protected user profile is incomplete.") from exc
        if not profile.completed:
            raise ProfileProtectionError("Protected user profile is incomplete.")
        return profile

    def public_status(self) -> dict[str, object]:
        profile = self.load()
        if profile is None:
            return {
                "completed": False,
                "language": None,
                "phone_registered": False,
            }
        return profile.public_status()

    def create_first_run(
        self,
        *,
        language: object,
        phone: object,
        own_number_confirmed: object,
        future_calls_authorized: object,
    ) -> UserProfile:
        if self.profile_file.exists():
            raise ProfileAlreadyExistsError(
                "A completed user profile already exists."
            )
        if language not in SUPPORTED_LANGUAGES:
            raise ProfileValidationError("Choose English or Japanese.")
        if own_number_confirmed is not True:
            raise ProfileValidationError("Confirm that this is your own number.")
        if future_calls_authorized is not True:
            raise ProfileValidationError(
                "Confirm that CALL-E may deliver your scheduled future calls."
            )
        profile = UserProfile(
            language=str(language),
            phone_e164=normalize_phone(phone),
            own_number_confirmed=True,
            future_calls_authorized=True,
            created_at=datetime.now().astimezone().isoformat(),
        )
        record = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "language": profile.language,
            "phone_e164": profile.phone_e164,
            "own_number_confirmed": profile.own_number_confirmed,
            "future_calls_authorized": profile.future_calls_authorized,
            "created_at": profile.created_at,
        }
        plaintext = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        protected = self.protector.protect(plaintext)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.profile_file.with_suffix(".dpapi.tmp")
        try:
            temporary.write_bytes(protected)
            if self.profile_file.exists():
                raise ProfileAlreadyExistsError(
                    "A completed user profile already exists."
                )
            temporary.replace(self.profile_file)
        finally:
            if temporary.exists():
                temporary.unlink()
        return profile

    def require_complete(self) -> UserProfile:
        profile = self.load()
        if profile is None:
            raise ProfileError("A registered user profile is required.")
        return profile
