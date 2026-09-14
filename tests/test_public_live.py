import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from public_dispatch_due import build_public_persistent_context
from public_web import parse_browser_schedule, validate_public_schedule


class PublicLivePolicyTests(unittest.TestCase):
    def test_browser_timezone_becomes_absolute_instant(self):
        value = parse_browser_schedule("2026-09-15 12:30", "Asia/Tokyo")
        self.assertEqual(value, datetime(2026, 9, 15, 3, 30, tzinfo=timezone.utc))

    def test_four_hour_minimum_is_enforced(self):
        now = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
        target = datetime(2026, 9, 14, 3, 59, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            validate_public_schedule(target, now=now)

    def test_public_dispatch_end_is_a_real_booking_boundary(self):
        now = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {"PUBLIC_DISPATCH_END_AT": "2026-09-20T00:00:00+00:00"},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                validate_public_schedule(
                    datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc),
                    now=now,
                )

    def test_persistent_context_contains_only_supplied_same_user_history(self):
        previous = [
            {
                "summary": "The user mentioned finishing a difficult edit.",
                "relationship_trace": "You made it through that edit.",
            }
        ]
        context = build_public_persistent_context(previous, "Ask if I ate lunch.")
        self.assertIn("finishing a difficult edit", context)
        self.assertIn("Ask if I ate lunch", context)
        self.assertNotIn("another user", context.lower())


if __name__ == "__main__":
    unittest.main()
