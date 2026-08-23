import json
from datetime import datetime
from pathlib import Path

from booking_policy import effective_minimum_minutes

DATA_DIR = Path("data")
PENDING_FILE = DATA_DIR / "pending_call.json"
CANCELLED_FILE = DATA_DIR / "cancelled_calls.jsonl"

MIN_HOURS = 4


def max_future_datetime(now):
    try:
        return now.replace(year=now.year + 10)
    except ValueError:
        return now.replace(year=now.year + 10, day=28)


def load_pending():
    if not PENDING_FILE.exists():
        return None

    return json.loads(
        PENDING_FILE.read_text(encoding="utf-8")
    )


def save_pending(record):
    PENDING_FILE.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def show_pending(record):
    print()
    print("=== PENDING FUTURE CALL ===")
    print("scheduled_for:", record.get("scheduled_for"))
    print("future_message:", record.get("future_message"))
    print("status:", record.get("status"))


def change_pending(record):
    now = datetime.now().astimezone()
    minimum_minutes = effective_minimum_minutes()

    print()
    print("Enter the new future call time as YYYY-MM-DD HH:MM")
    raw_time = input("New future call time: ").strip()

    try:
        naive_target = datetime.strptime(
            raw_time,
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        print("INVALID_DATETIME_FORMAT")
        return

    target = naive_target.replace(tzinfo=now.tzinfo)

    if (target - now).total_seconds() < minimum_minutes * 60:
        print("TOO_SOON")
        return

    if target > max_future_datetime(now):
        print("TOO_FAR")
        return

    old_time = record.get("scheduled_for")

    history = record.setdefault("change_history", [])
    history.append({
        "from": old_time,
        "to": target.isoformat(),
        "changed_at": now.isoformat(),
    })

    record["scheduled_for"] = target.isoformat()
    record["updated_at"] = now.isoformat()

    save_pending(record)

    print()
    print("LOCAL_CHANGE=PASS")
    print("from:", old_time)
    print("to:", record["scheduled_for"])


def cancel_pending(record):
    now = datetime.now().astimezone()

    record["status"] = "cancelled_local"
    record["cancelled_at"] = now.isoformat()

    with CANCELLED_FILE.open(
        "a",
        encoding="utf-8"
    ) as f:
        f.write(
            json.dumps(
                record,
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )

    PENDING_FILE.unlink()

    print()
    print("LOCAL_CANCEL=PASS")
    print("Pending slot is now empty.")
    print("Cancellation archived to:", CANCELLED_FILE)


def main():
    DATA_DIR.mkdir(exist_ok=True)

    record = load_pending()

    if record is None:
        print("NO_PENDING_CALL")
        return

    show_pending(record)

    print()
    print("Choose an action:")
    print("1 = show only")
    print("2 = change")
    print("3 = cancel")

    choice = input("Action: ").strip()

    if choice == "1":
        print("SHOW=PASS")
    elif choice == "2":
        change_pending(record)
    elif choice == "3":
        cancel_pending(record)
    else:
        print("INVALID_ACTION")


if __name__ == "__main__":
    main()
