# CALL-E usual AI persistence

`usual_ai.py` is a persistence and prompt-context layer. It never calls CALL-E.
`dispatch_call.py` now uses it immediately before a real call task is submitted
and immediately after the normal saved result/history and pending-slot cleanup.

It persists four small files under `data/usual_ai/` by default:

- `ai_identity.json`: the AI's first self-chosen name and origin.
- `shared_history.jsonl`: concise evidence-linked events, without transcript text.
- `relationship_state.json`: independent, tentative behavioral hypotheses.
- `processed_calls.json`: source digests that make post-call updates idempotent.

Process an already-saved result:

```powershell
python usual_ai_cli.py update results\scheduled_call_YYYYMMDD_HHMMSS.json
```

Generate context suitable for later insertion into the existing call task:

```powershell
python usual_ai_cli.py context --future-message "optional reservation context"
```

The current extractor is deterministic scaffolding. It only recognizes explicit
self-naming that a later user turn affirmatively acknowledges or naturally uses,
ordinary-event markers, laughter following an AI turn, explicit
forms of address, short/topicless contact, and explicit boundary/repair language.
Future OpenAI inference can propose structured candidates, but persistence should
continue to require concise evidence and should never store an intimacy score.

## Dispatcher boundaries

Pre-call context is capped at 4,500 characters and placed inside an explicit
prompt boundary. Stored event summaries and optional user context are evidence,
not instructions that can override the core call task.

After a completed call, the dispatcher keeps its original ordering for normal
result/history persistence and pending-slot cleanup. It then invokes the memory
update once. If memory processing fails, the already-saved call remains complete,
the pending slot stays cleared, and a `memory_update_failure_*.json` sidecar records
that no call retry is authorized.

## Isolated web QA

An isolated API must set all of these variables:

- `CALL_E_STORAGE_MODE=isolated`
- `CALL_E_DATA_ROOT=<absolute temporary ...\data path>`
- `CALL_E_RESULTS_ROOT=<absolute temporary results path>`
- `CALL_E_INSTANCE_ID=<unique non-secret test-run id>`

Set `VITE_CALL_E_QA_INSTANCE_ID` to the same test-run id for frontend QA. Before
every mutation the frontend verifies `/api/health`; it refuses to write if a
stale or real-data localhost process answers instead. The server also requires
the matching instance header and rejects QA-tagged writes in real mode.
