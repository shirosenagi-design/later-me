from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")
GIT = shutil.which("git.exe") or shutil.which("git")


class JudgeBuildTests(unittest.TestCase):
    def run_powershell(
        self,
        script: str,
        *arguments: str,
        input_text: str | None = None,
        environment: dict[str, str] | None = None,
        cwd: Path = APP_ROOT,
    ) -> subprocess.CompletedProcess[str]:
        assert POWERSHELL is not None
        return subprocess.run(
            [
                POWERSHELL,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(APP_ROOT / script),
                *arguments,
            ],
            cwd=cwd,
            input=input_text,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def run_with_isolated_protector(
        self,
        mode: str,
        secret_root: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Exercise the storage contract when DPAPI is unavailable to automation.

        The replacement functions exist only inside this child test process.
        Product code continues to call Windows ConvertFrom/To-SecureString.
        """
        assert POWERSHELL is not None
        script = r"""
function ConvertTo-SecureString {
    param(
        [Parameter(Position=0)][string]$String,
        [switch]$AsPlainText,
        [switch]$Force
    )
    if ($AsPlainText) {
        $plain = $String
    }
    else {
        $plain = [Text.Encoding]::UTF8.GetString(
            [Convert]::FromBase64String($String)
        )
    }
    $secure = [Security.SecureString]::new()
    foreach ($character in $plain.ToCharArray()) {
        $secure.AppendChar($character)
    }
    $secure.MakeReadOnly()
    return $secure
}
function ConvertFrom-SecureString {
    param([Parameter(Mandatory=$true)][Security.SecureString]$SecureString)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($plain))
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}
if ($env:JUDGE_SECRET_MODE -eq "api") {
    & $env:JUDGE_SAVE_SCRIPT -ApiKeyOnly -SecretRoot $env:JUDGE_SECRET_ROOT
}
elseif ($env:JUDGE_SECRET_MODE -eq "openai") {
    & $env:JUDGE_SAVE_SCRIPT -OpenAIOnly -SecretRoot $env:JUDGE_SECRET_ROOT
}
else {
    throw "Unknown isolated test mode."
}
exit $LASTEXITCODE
"""
        child_environment = dict(environment)
        child_environment["JUDGE_SAVE_SCRIPT"] = str(APP_ROOT / "save_secrets.ps1")
        child_environment["JUDGE_SECRET_MODE"] = mode
        child_environment["JUDGE_SECRET_ROOT"] = str(secret_root)
        return subprocess.run(
            [
                POWERSHELL,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            cwd=APP_ROOT,
            env=child_environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    @unittest.skipUnless(
        os.name == "nt" and POWERSHELL,
        "Windows CurrentUser DPAPI requires Windows PowerShell.",
    )
    def test_key_only_and_openai_only_storage_contract_is_isolated(self) -> None:
        call_e_secret = "synthetic_calle_secret_value_for_judge_test"
        openai_secret = "synthetic_openai_secret_value_for_judge_test"
        with tempfile.TemporaryDirectory() as temporary:
            secret_root = Path(temporary) / "secrets"
            call_e_environment = dict(os.environ)
            call_e_environment["CALLE_API_KEY"] = call_e_secret
            call_e_environment.pop("CALLE_TEST_PHONE", None)
            call_e_environment.pop("OPENAI_API_KEY", None)
            call_e = self.run_with_isolated_protector(
                "api",
                secret_root,
                environment=call_e_environment,
            )
            self.assertEqual(call_e.returncode, 0, call_e.stderr)
            combined = call_e.stdout + call_e.stderr
            self.assertNotIn(call_e_secret, combined)
            self.assertIn("DPAPI_SAVE=PASS", combined)
            self.assertIn("PHONE_SAVED= False", combined)
            self.assertTrue((secret_root / "calle_api_key.dpapi").is_file())
            self.assertFalse((secret_root / "calle_phone.dpapi").exists())

            openai_environment = dict(os.environ)
            openai_environment["OPENAI_API_KEY"] = openai_secret
            openai_environment.pop("CALLE_API_KEY", None)
            openai_environment.pop("CALLE_TEST_PHONE", None)
            openai = self.run_with_isolated_protector(
                "openai",
                secret_root,
                environment=openai_environment,
            )
            self.assertEqual(openai.returncode, 0, openai.stderr)
            combined = openai.stdout + openai.stderr
            self.assertNotIn(openai_secret, combined)
            self.assertIn("DPAPI_SAVE=PASS", combined)
            self.assertTrue((secret_root / "openai_api_key.dpapi").is_file())
            self.assertFalse((secret_root / "calle_phone.dpapi").exists())

    @unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows launcher test")
    def test_judge_start_self_test_keeps_production_timing(self) -> None:
        completed = self.run_powershell("judge_start.ps1", "-SelfTest")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout + completed.stderr
        self.assertIn("CALL_E_STORAGE_MODE=real", output)
        self.assertIn("CALL_E_DELIVERY_MODE=live", output)
        self.assertIn("CALL_E_DEV_SHORT_HORIZON=0", output)
        self.assertIn("PRODUCTION_MINIMUM_HOURS=4", output)
        self.assertIn("OPENAI_REQUIRED=NO", output)
        self.assertIn("EXTERNAL_API_REQUEST_SENT=NO", output)
        self.assertIn("REAL_CALL_SENT=NO", output)

    @unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows setup test")
    def test_judge_setup_self_test_is_non_mutating(self) -> None:
        completed = self.run_powershell("judge_setup.ps1", "-SelfTest")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout + completed.stderr
        self.assertIn("JUDGE_SETUP_SELF_TEST=PASS", output)
        self.assertIn("PYTHON_3_13_AVAILABLE=YES", output)
        self.assertIn("NODE_VERSION_SUPPORTED=YES", output)
        self.assertIn("SYSTEM_INSTALL_PERFORMED=NO", output)
        self.assertIn("CREDENTIAL_PROMPT_USED=NO", output)
        self.assertIn("EXTERNAL_API_REQUEST_SENT=NO", output)
        self.assertIn("REAL_CALL_SENT=NO", output)

    def test_launchers_do_not_dispatch_or_load_secrets(self) -> None:
        start = (APP_ROOT / "judge_start.ps1").read_text(encoding="utf-8")
        self.assertNotIn("--execute-call", start)
        self.assertNotIn("load_secrets.ps1", start)
        self.assertNotIn("OPENAI_API_KEY", start)
        self.assertIn('$env:CALL_E_DEV_SHORT_HORIZON = "0"', start)

    def test_openai_setup_no_longer_requires_legacy_phone_blob(self) -> None:
        setup = (APP_ROOT / "setup_openai_key.ps1").read_text(encoding="utf-8")
        self.assertIn("-OpenAIOnly -Interactive", setup)
        self.assertNotIn("load_secrets.ps1", setup)
        judge_setup = (APP_ROOT / "judge_secret_setup.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("-ApiKeyOnly -Interactive", judge_setup)
        self.assertIn("-OpenAIOnly -Interactive", judge_setup)
        self.assertNotIn("CALLE_TEST_PHONE", judge_setup)

    def test_setup_never_auto_installs_system_runtimes(self) -> None:
        setup = (APP_ROOT / "judge_setup.ps1").read_text(encoding="utf-8")
        lowered = setup.casefold()
        self.assertNotIn("winget install", lowered)
        self.assertNotIn("choco install", lowered)
        self.assertNotIn("msiexec", lowered)
        self.assertIn("https://www.python.org/downloads/windows/", setup)
        self.assertIn("https://nodejs.org/en/download", setup)

    @unittest.skipUnless(os.name == "nt" and POWERSHELL and GIT, "Windows Git test")
    def test_package_manifest_uses_only_an_isolated_committed_tree(self) -> None:
        required = {
            ".gitignore",
            "README.md",
            "LICENSE",
            "COMMERCIAL_USE.md",
            "ART_PROVENANCE.md",
            "JUDGE_QUICKSTART.md",
            "judge_setup.cmd",
            "judge_setup.ps1",
            "judge_secret_setup.ps1",
            "judge_start.cmd",
            "judge_start.ps1",
            "build_judge_package.ps1",
            "requirements.txt",
            "save_secrets.ps1",
            "load_secrets.ps1",
            "web_api.py",
            "dispatch_call.py",
            "run_dispatch.ps1",
            "register_live_task.ps1",
            "web/package.json",
            "web/package-lock.json",
            "web/src/main.tsx",
            "public.txt",
        }
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            for relative in required:
                destination = repository / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("public fixture\n", encoding="utf-8")
            (repository / ".gitignore").write_text("data/\n*.zip\n", encoding="utf-8")
            private = repository / "data" / "private.dpapi"
            private.parent.mkdir(parents=True, exist_ok=True)
            private.write_text("private fixture\n", encoding="utf-8")
            (repository / "untracked-local.txt").write_text(
                "local fixture\n", encoding="utf-8"
            )

            commands = (
                [GIT, "-C", str(repository), "init", "-q"],
                [GIT, "-C", str(repository), "add", "--", *sorted(required)],
                [
                    GIT,
                    "-C",
                    str(repository),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture",
                    "commit",
                    "-q",
                    "-m",
                    "fixture",
                ],
            )
            for command in commands:
                completed = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

            manifest = self.run_powershell(
                "build_judge_package.ps1",
                "-RepositoryRoot",
                str(repository),
                "-ManifestOnly",
            )
            self.assertEqual(manifest.returncode, 0, manifest.stderr)
            output = manifest.stdout + manifest.stderr
            self.assertIn("JUDGE_PACKAGE_MANIFEST=PASS", output)
            self.assertIn("PACKAGE_FILE=public.txt", output)
            self.assertNotIn("private.dpapi", output)
            self.assertNotIn("untracked-local.txt", output)
            self.assertFalse(any(repository.rglob("*.zip")))

    def test_quickstart_states_current_product_boundaries(self) -> None:
        quickstart = (APP_ROOT / "JUDGE_QUICKSTART.md").read_text(encoding="utf-8")
        normalized = " ".join(quickstart.split())
        self.assertIn("at least 4 hours", normalized)
        self.assertIn("Only one future call", normalized)
        self.assertIn("Do not move the folder after scheduling", normalized)
        self.assertIn("OpenAI is optional", normalized)
        self.assertIn("CALL-E performs the actual outbound phone experience", normalized)


if __name__ == "__main__":
    unittest.main()
