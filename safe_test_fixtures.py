"""Shared sentinels that are intentionally unusable as real call targets."""

import re


TEST_ONLY_PHONE = "<TEST_PHONE_DO_NOT_DIAL>"
_E164_SHAPE = re.compile(r"\+[1-9][0-9]{7,14}\Z")

if _E164_SHAPE.fullmatch(TEST_ONLY_PHONE):
    raise AssertionError("The test-only phone sentinel must never be E.164-shaped.")
