# Later, Me. — Public Live Hackathon Trial

This overlay turns the existing localhost/Windows judge build into a separate, limited public-live path without deleting or replacing the original implementation.

## What is real in this build

- Visitor chooses Japanese or English.
- Visitor registers their own E.164 phone number and consents to the future call.
- Reservation is stored in Render Postgres, not browser localStorage.
- A finite real-call slot is reserved at booking time.
- At the due time, a Render Cron Job calls the real CALL-E API.
- CALL-E terminal status, summary and transcript are persisted before any OpenAI post-processing.
- OpenAI Responses API is then used for the existing Relationship Trace decision.
- The visitor's Past Calls view is built from actual persisted call attempts/results only.
- There are no fake/demo/sample call records.

## Finite public trial controls

`CALL_E_MAX_CALLS` is the hard global number of real CALL-E attempts that the public trial may accept. A slot is reserved when a booking is created, not when it is dispatched, so the site cannot overbook more calls than the configured cap.

`PUBLIC_BOOKING_CLOSE_AT` is the final instant at which new reservations may be created.

`PUBLIC_DISPATCH_END_AT` is the latest call time the public site will accept. Use ISO-8601 with timezone, for example `2026-10-01T23:59:00+09:00`.

A canceled pending reservation returns its unused slot. Once a due reservation is claimed for CALL-E dispatch, that slot is consumed and automatic retry is forbidden even if delivery fails or becomes indeterminate.

Each phone number can register only once during the public trial, which also reduces repeated-call abuse.

## Render Blueprint prompts

When creating the Blueprint, Render prompts for:

- Web service: `CALL_E_MAX_CALLS`, `PUBLIC_BOOKING_CLOSE_AT`, `PUBLIC_DISPATCH_END_AT`
- Cron job: `CALL_E_API_KEY`, `OPENAI_API_KEY`

`PHONE_ENCRYPTION_KEY` is generated automatically once in a shared Render environment group and is never committed.

## Cost boundary

Choose `CALL_E_MAX_CALLS` from the amount of CALL-E usage you are actually willing to fund. The application-side cap is intentionally independent of provider billing so the public site itself cannot schedule an unlimited number of calls.

OpenAI Relationship Trace inference runs at most once for each completed CALL-E call and never authorizes a retry of the phone call.

## Important limitation

CALL-E itself may reject destinations that are unavailable under its current country/language/risk controls. Such attempts are stored as real failures; the application never pretends a rejected call succeeded.
