from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from safe_test_fixtures import TEST_ONLY_PHONE


APP_ROOT = Path(__file__).resolve().parents[1]
PHONE_SHAPE = re.compile(r"(?<![A-Za-z0-9])\+[1-9](?:[\s-]?\d){7,14}(?!\d)")
PUBLIC_TEXT_SUFFIXES = {".py", ".ps1", ".md", ".ts", ".tsx", ".js", ".json"}
IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "data",
    "dist",
    "logs",
    "node_modules",
    "results",
}


class PublicSourceFixtureTests(unittest.TestCase):
    def test_shared_phone_fixture_is_not_dialable_syntax(self) -> None:
        self.assertIsNone(PHONE_SHAPE.fullmatch(TEST_ONLY_PHONE))
        self.assertFalse(TEST_ONLY_PHONE.startswith("+"))

    def test_public_source_contains_no_phone_shaped_literals(self) -> None:
        findings: list[str] = []
        for root, directories, filenames in os.walk(APP_ROOT, topdown=True):
            directories[:] = [
                name
                for name in directories
                if name not in IGNORED_PARTS and not name.startswith(".qa-")
            ]
            for filename in filenames:
                path = Path(root) / filename
                if path.suffix.lower() not in PUBLIC_TEXT_SUFFIXES:
                    continue
                relative = path.relative_to(APP_ROOT)
                text = path.read_text(encoding="utf-8-sig")
                if PHONE_SHAPE.search(text):
                    findings.append(str(relative))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
