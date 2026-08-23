from datetime import datetime, timedelta, timezone


def is_due(scheduled_for: str, now: datetime) -> bool:
    scheduled = datetime.fromisoformat(scheduled_for)

    if scheduled.tzinfo is None:
        raise ValueError("scheduled_for must include timezone")

    if now.tzinfo is None:
        raise ValueError("now must include timezone")

    return now >= scheduled


if __name__ == "__main__":
    JST = timezone(timedelta(hours=9))

    scheduled = "2026-08-21T03:00:00+09:00"

    tests = [
        (
            "BEFORE",
            datetime(2026, 8, 21, 2, 59, 59, tzinfo=JST),
            False,
        ),
        (
            "EXACT",
            datetime(2026, 8, 21, 3, 0, 0, tzinfo=JST),
            True,
        ),
        (
            "AFTER",
            datetime(2026, 8, 21, 3, 0, 1, tzinfo=JST),
            True,
        ),
    ]

    all_passed = True

    for name, now, expected in tests:
        actual = is_due(scheduled, now)
        passed = actual == expected

        print(
            f"{name}: "
            f"expected={expected} "
            f"actual={actual} "
            f"{'PASS' if passed else 'FAIL'}"
        )

        if not passed:
            all_passed = False

    print()

    if all_passed:
        print("DUE_LOGIC=PASS")
    else:
        print("DUE_LOGIC=FAIL")
