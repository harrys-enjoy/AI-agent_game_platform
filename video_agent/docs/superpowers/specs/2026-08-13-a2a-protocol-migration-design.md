# A2A 1.0 protocol migration — video-agent compliance with the team's Notion spec

## Context

On 2026-08-12 the team confirmed it is unifying all agents (Workmate, video-generation, Dev, Game Q&A) on a formal A2A 1.0 protocol documented by a teammate on Notion (`# A2A 개발을 위한 팀 공통 개발 규약`). This has been a doc floating disconnected from the actual implementation until now — direct comparison against video-agent's real code (`a2a_server/app.py`, `tasks.py`, `agent_card.py`) and Main Agent's real client (`registry.py`) found significant drift (see below). Workmate and Dev agents are listed "Mock" in the doc's own status table and their authors haven't pushed a GitHub branch yet — they are out of scope here.

**Scope decision (explicit, from brainstorming session):** this spec covers **video-agent only** (`video_draft_pipeline`). Main Agent (`AI-agent_game_platform`) is being rewritten by a teammate to speak the new protocol as part of the same frontend-architecture pivot already underway (see `[[project_64_frontend_architecture_pivot]]`) — two people editing both ends of the same wire contract would just reproduce the drift we're fixing. This spec targets the Notion doc itself as the contract, not the teammate's current (soon to be replaced) client code.

**Cutover strategy (explicit decision):** hard cutover. Video-agent ships the new wire format in one release; no dual-format transition period. Main Agent's current integration will be stale against video-agent until the teammate's rewrite lands — acceptable since that rewrite is already happening for unrelated reasons.

### Confirmed drift (doc vs. code, verified by direct read)

- **Route prefix:** doc §5 mandates all 3 A2A operations live under `http://{service}:{port}/a2a`. Video-agent's server mounts everything at root — no `/a2a` prefix anywhere.
- **Agent Card:** `agent_card.py` is internally inconsistent — `url` claims `{internal_url}/a2a`, `supportedInterfaces[0].url` claims `{internal_url}/message:send`. Neither matches doc §8's required shape (`supportedInterfaces[0].url == {internal_url}/a2a`, `protocolBinding`, `protocolVersion` fields).
- **Task states:** doc §12 defines 8 states. `TaskStore` (`tasks.py`) only ever sets 3 (`_WORKING`/`_COMPLETED`/`_FAILED`). The manual-fix flow misuses `_COMPLETED` with `unresolvedScenes` bolted on instead of `TASK_STATE_INPUT_REQUIRED`.
- **Message envelope:** doc §10 requires `messageId`, `role`, `parts[].mediaType`, `configuration.acceptedOutputModes`, `metadata.request_id`. The real `/message:send` handler's `_extract_text()` reads only `.parts[].text`, ignoring everything else.
- **Artifacts:** doc §11 requires results in `task.artifacts[].parts[]`. Real responses are ad hoc (`{"task": {"id", "status"}}`, raw `unresolvedScenes` list).
- **Auth:** doc §15 mandates `Authorization: Bearer {service-token}` + `A2A-Version: 1.0`. Nothing on video-agent's server validates either today (client-side Bearer support exists in Main Agent's `registry.py`, unenforced server-side).
- **Cancel:** doc §5 requires `POST /tasks/{id}:cancel`. Doesn't exist; the pipeline has no cancellation hook.
- **Idempotency:** doc §16 requires retry-safe handling of a repeated `messageId`. No such tracking exists.

## Goals

- Video-agent's `/a2a/*` surface matches the Notion doc's §5 route shape, §8 Agent Card shape, §10 Message envelope, §11 Artifact response shape, §12 full 8-state task model, §15 Bearer + `A2A-Version` auth, and §16 `messageId` idempotency.
- Fix the manual-fix flow to correctly report `TASK_STATE_INPUT_REQUIRED` instead of misusing `COMPLETED` — a genuine correctness fix, not just protocol compliance.
- Add a coarse `POST /a2a/tasks/{id}:cancel` — accept the request, stop dispatching further pipeline stages; not true mid-flight interruption of a running Gemini/Veo call.

## Non-goals

- Any change to Main Agent (`AI-agent_game_platform`) — teammate's responsibility, out of scope.
- Workmate/Dev agent compliance — not yet built (doc status: "Mock"), no branch pushed.
- Streaming, push notifications, gRPC, multi-binding — doc §19 explicitly excludes these from MVP.
- True mid-flight cancellation of an in-progress Gemini/Veo API call — coarse "stop before next stage" only.
- Real conversation/session state for `contextId` correlation across multiple clarifying-question turns — see "contextId" below.
- Any change to the render pipeline itself (`orchestrator.py`'s scene logic, `agents/`, `render_backends/`) beyond the one cancellation checkpoint described below.

## Design

### Package layout

```
a2a_server/
  protocol.py    NEW — pydantic models (Message, Part, TaskState enum, TaskStatus, Task, Artifact)
                  + parse_message_send_request() / build_task_response() / build_video_artifact() /
                  build_unresolved_artifacts()
  auth.py         NEW — FastAPI dependency: validates Authorization: Bearer {VIDEO_SERVICE_TOKEN}
                  and A2A-Version: 1.0; mounted only on the 3 /a2a/* routes
  app.py          routes reorganized: 3 canonical ops under /a2a/*, resume-upload + agent-card
                  stay unprefixed (see "Route boundary" below); route bodies become thin —
                  parse via protocol.py, call existing render_runner/orchestrator, build
                  response via protocol.py
  tasks.py        TaskRecord gains: state: TaskState (all 8), context_id, cancel_requested: bool;
                  TaskStore gains a messageId -> task_id map for idempotency
  agent_card.py   fixed so url and supportedInterfaces[0].url both point at {internal_url}/a2a,
                  matching doc §8 exactly
  errors.py       STATUS_HTTP_CODES gains UNAUTHENTICATED: 401, PERMISSION_DENIED: 403
  render_runner.py, orchestrator.py, schema.py   unchanged, except one addition to
                  orchestrator.run_pipeline() — see "Cancel" below
```

### Route boundary

Doc §5 lists exactly 3 operations under `/a2a`, and §5 explicitly prohibits inventing extra A2A paths (gives `/run`, `/execute`, `/ask`, `/chat` as the banned pattern). Doc §18 draws the line: *A2A endpoints own protocol/schema validation; UI API owns file uploads and screen requests.*

- **Move under `/a2a`:** `POST /a2a/message:send`, `GET /a2a/tasks/{id}`, `POST /a2a/tasks/{id}:cancel`.
- **Stay unprefixed, outside `/a2a`:** `GET /.well-known/agent-card.json` (doc §7 fixes this exact path), `POST /tasks/{task_id}/scenes/{scene_id}/resume` (a file upload — doc §18 assigns this to UI API, not A2A), the `/media` static mount.

`POST /tasks/{id}/scenes/{id}/resume` is called directly by Main Agent's backend to proxy a browser image upload — it is not part of the Orchestrator's A2A client traffic, so it correctly sits outside the protocol surface rather than being force-fit into it.

### Task states (doc §12)

All 8 states added to a `TaskState` enum. Mapping to video-agent's actual pipeline:

| State | Video-agent trigger |
|---|---|
| `SUBMITTED` | Task record created, before background render starts |
| `WORKING` | Render pipeline running |
| `INPUT_REQUIRED` | **Fixed bug**: manual-fix flow (`needs_manual_fix` scenes) now correctly lands here instead of `COMPLETED` |
| `COMPLETED` | Render finished, no manual fixes needed, or all manual fixes resolved via resume |
| `FAILED` | `PipelineError` or unexpected exception |
| `CANCELED` | Cancel endpoint accepted before the pipeline finished |
| `AUTH_REQUIRED` | Not reachable by video-agent's pipeline today — included for schema completeness, never set |
| `REJECTED` | Not reachable today — included for schema completeness, never set |

Resuming a scene (`POST /tasks/{id}/scenes/{id}/resume`) now moves the task back to `WORKING` if other scenes still need fixes, or to `COMPLETED` if that was the last one, instead of the caller inferring completion from `remaining_unresolved` being empty.

Per doc §12, errors that occur **before a task exists** (malformed envelope, auth failure) return as raw HTTP 400/401/403 — not wrapped in a task/error JSON body. `errors.py`'s existing `error_response()` already does this correctly (proper HTTP status + JSON body); it just needs `401`/`403` added to `STATUS_HTTP_CODES`.

### Message envelope and artifacts (doc §10, §11)

`protocol.py` defines the full envelope: `Message` (`messageId`, `role`, `parts: list[Part]`, `configuration.acceptedOutputModes`, `metadata.request_id`), `Part` (`text` or `data`, plus `mediaType`), `Task` (`id`, `contextId`, `status`, `artifacts: list[Artifact]`), `Artifact` (`artifactId`, `name`, `parts: list[Part]`).

`parse_message_send_request(body) -> Message` replaces `_extract_text()`; validates the full envelope and raises `INVALID_ARGUMENT` (400) for a missing `messageId`, bad `role`, or empty `parts`, instead of today's silent ignore-everything-but-text.

Responses move from ad hoc dicts to real artifacts:
- Completed render → one `Artifact` with a `text/markdown` part (Korean summary) and an `application/json` part (`{output_video_url}`).
- Manual-fix-needed → one `Artifact` per unresolved scene, or one artifact carrying the existing `unresolvedScenes`-shaped list as its JSON part (exact shape decided during implementation — either is doc-compliant since §11 only fixes the outer `artifacts[].parts[]` envelope, not the inner JSON payload's schema).

### `contextId`

Doc §11's example includes `task.contextId`; §17 defines it as conversation/work context. Video-agent's intake flow doesn't carry multi-turn state server-side today (each clarifying-question round is an independent stateless call) — so this pass does **not** build real conversation correlation. `context_id` is generated once a task is created and carried through as an opaque value, satisfying the schema without inventing session state that doesn't exist yet. Flagged as a deliberate scope cut, not an oversight.

### Auth (doc §15)

`auth.py`: a FastAPI dependency mounted only on the 3 `/a2a/*` routes. Reads `VIDEO_SERVICE_TOKEN` from the environment (matches the doc §4 Docker Compose env var naming). Validates `Authorization: Bearer {token}` and `A2A-Version: 1.0` on every request; missing or mismatched → `401` via `error_response("UNAUTHENTICATED", ...)`.

Not applied to `/tasks/{id}/scenes/{id}/resume` (UI-API territory, out of the A2A auth boundary per §18) or the agent card (doc doesn't require protecting it).

### Idempotency (doc §16)

`TaskStore` gains `message_id_to_task: dict[str, str]`. On `POST /a2a/message:send`, if the incoming `messageId` has been seen before, return the existing task's current state instead of dispatching a second render — prevents a client-side network retry from double-billing Gemini/Veo calls.

### Cancel (doc §5, §12)

`POST /a2a/tasks/{id}:cancel`: marks `TaskRecord.cancel_requested = True`, returns the task in `CANCELED` state immediately (coarse accept). One necessary addition to `orchestrator.run_pipeline()`: an optional `should_cancel: Callable[[], bool]` parameter, checked between scene iterations; if true, stops dispatching further scenes and returns what's completed so far. `render_runner` marks the task `CANCELED` instead of `COMPLETED`/`FAILED` when this happens. This is the one exception to "pipeline package unchanged" — everything else about scene processing logic is untouched.

## Testing

- `tests/a2a_server/test_protocol.py` — `protocol.py`'s parse/build functions in isolation: valid envelope round-trips, missing `messageId`/`role`/empty `parts` all raise `INVALID_ARGUMENT`, artifact builders produce the exact `artifacts[].parts[]` shape from doc §11.
- `tests/a2a_server/test_auth.py` — `auth.py` dependency: valid Bearer + `A2A-Version` passes; missing/wrong token → 401; missing/wrong `A2A-Version` → 401; confirms auth is NOT applied to resume-upload or agent-card routes.
- `tests/a2a_server/test_tasks.py` — extend existing coverage: all 8 states settable, `messageId` dedup returns the same task without re-dispatching a render (stub render_fn call-count assertion), manual-fix flow reports `INPUT_REQUIRED` not `COMPLETED`.
- `tests/a2a_server/test_app.py` — FastAPI `TestClient` integration: routes under `/a2a/*` require auth, resume-upload route does not, cancel endpoint transitions state and stops a stubbed multi-scene pipeline partway through.
- `tests/a2a_server/test_agent_card.py` — update existing assertions: `url` and `supportedInterfaces[0].url` both equal `{internal_url}/a2a`.
- `scripts/a2a_server_smoke_test.py` (manual, real billed calls) — update to call `/a2a/message:send` with a full envelope and real Bearer token, confirming the whole stack end-to-end.

## Open questions / follow-ups (not blocking this spec)

- Exact inner JSON payload shape for the manual-fix artifact (per-scene array vs. one artifact per scene) — left to implementation judgment, either is doc-compliant.
- Whether `A2A-Version` mismatches (e.g. a future `2.0` client) should be rejected or just logged — doc doesn't specify; defaulting to reject (400) since MVP only supports `1.0`.
- Coordinating the actual cutover moment with the teammate rewriting Main Agent so the gap window (video-agent on new format, Main Agent still on old) is short — a scheduling conversation, not a code question.
- Workmate/Dev agent compliance — explicitly out of scope until those repos exist.
