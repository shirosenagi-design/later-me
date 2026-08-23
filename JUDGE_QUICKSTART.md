# Later, Me. — Judge Quickstart

Later, Me. is a localhost-only Windows hackathon prototype. CALL-E performs the
actual outbound phone experience. OpenAI is optional and is currently used only
for post-call Relationship Trace reasoning—not for the live conversation.

## Requirements

- Windows 10 or 11
- CPython 3.13
- Node.js `^20.19.0` or `>=22.12.0`, with npm
- Your own CALL-E API credential
- Optionally, your own OpenAI API key for post-call Relationship Trace
- Permission to register a one-shot Windows Scheduled Task

The setup does not install Python or Node.js system-wide. If either runtime is
missing or unsupported, it stops and points you to the official download site.

## Setup

1. Extract Later, Me. into its **final location**.
2. Run `judge_setup.cmd`.
3. Confirm the folder location, then let setup create `.venv`, install pinned
   Python packages, run `npm ci`, and verify the frontend build.
4. Enter your CALL-E API key in the hidden prompt.
5. Choose whether to enter an optional OpenAI API key, also in a hidden prompt.
6. Run `judge_start.cmd`.
7. Complete onboarding in the browser with your own phone number and consent.
8. Reserve one call at least 4 hours—and at most 10 years—ahead.

The API key is not accepted as a command-line argument or saved in `.env`. It
is encrypted for the current Windows user with DPAPI. Your phone number is not
part of credential setup; onboarding stores it separately in a DPAPI-protected
local profile.

## Important

**Do not move the folder after scheduling a call.** The Scheduled Task stores
the absolute package path at reservation time. Moving the folder can prevent
the scheduled call from running.

- Only one future call may be pending at a time.
- Keep the Windows PC available for the current local scheduler architecture.
- Use only a phone number that belongs to you.
- Runtime phone numbers, reservations, transcripts, results, and logs remain
  local and must not be uploaded or shared.
- OpenAI is optional. Without it, the CALL-E call and local result persistence
  still work; only post-call Relationship Trace is unavailable.
- No call is placed by setup or startup. A call becomes eligible only after you
  create a reservation in the UI and its scheduled time arrives.
- This is a hackathon prototype, not a production service.

## Troubleshooting

- **Python or Node.js rejected:** install the version shown by setup, then rerun
  `judge_setup.cmd`.
- **Port 8787 or 5173 is occupied:** stop the unrelated local process manually;
  the launcher will not terminate it for you.
- **Protected credential missing:** rerun `judge_setup.cmd` and enter your own
  CALL-E key.
- **Task registration fails:** check local Task Scheduler permission and the
  generic warning in the UI. Do not manually dispatch or create duplicate
  reservations.
- **Startup fails:** inspect the local `logs/judge_*_stderr.log` files. Never
  publish those logs because runtime data may be private.

For architecture, privacy boundaries, licensing, and safe isolated development,
see [README.md](README.md).
