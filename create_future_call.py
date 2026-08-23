import json
from datetime import datetime
from pathlib import Path

from booking_policy import DEFAULT_MINIMUM_MINUTES, effective_minimum_minutes

DATA_DIR = Path("data")
PENDING_FILE = DATA_DIR / "pending_call.json"

MIN_HOURS = 4


def max_future_datetime(now):
    try:
        return now.replace(year=now.year + 10)
    except ValueError:
        return now.replace(year=now.year + 10, day=28)


def main():
    DATA_DIR.mkdir(exist_ok=True)

    if PENDING_FILE.exists():
        print("PENDING_CALL_EXISTS")
        print(PENDING_FILE.read_text(encoding="utf-8"))
        print()
        print("A future call is already reserved.")
        print("Cancel or change it before creating another one.")
        return

    now = datetime.now().astimezone()
    minimum_minutes = effective_minimum_minutes()

    print("=== FUTURE CALL ===")
    print("Current local time:", now.strftime("%Y-%m-%d %H:%M %Z"))
    print("Enter the future call time as YYYY-MM-DD HH:MM")
    print(f"Minimum: {minimum_minutes} minutes from now")
    print("Maximum: 10 years from now")
    print()

    raw_time = input("Future call time: ").strip()

    try:
        naive_target = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
    except ValueError:
        print("INVALID_DATETIME_FORMAT")
        return

    target = naive_target.replace(tzinfo=now.tzinfo)

    seconds_ahead = (target - now).total_seconds()

    if seconds_ahead < minimum_minutes * 60:
        print("TOO_SOON")
        if minimum_minutes == DEFAULT_MINIMUM_MINUTES:
            print("Calls must be scheduled at least 4 hours in the future.")
        else:
            print(
                "This development session requires at least "
                f"{minimum_minutes} minutes of lead time."
            )
        return

    if target > max_future_datetime(now):
        print("TOO_FAR")
        print("Calls can be scheduled up to 10 years in the future.")
        return

    note = input(
        "Optional message/context for your future self "
        "(press Enter to leave blank): "
    ).strip()

    record = {
        "status": "pending_local",
        "scheduled_for": target.isoformat(),
        "created_at": now.isoformat(),
        "future_message": note or None,
        "call_id": None,
    }

    PENDING_FILE.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("LOCAL_RESERVATION=PASS")
    print("scheduled_for:", record["scheduled_for"])
    print("future_message:", record["future_message"])
    print("saved_to:", PENDING_FILE)


if __name__ == "__main__":
    main()
