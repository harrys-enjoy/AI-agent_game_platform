# A2A server — exposing video_draft_pipeline as a callable sub-agent

## Context

A teammate is building a separate "Main Agent" orchestrator (`AI-agent_game_platform`, cloned locally at `C:\Users\golgi\edu\AI-agent_game_platform`) with a Discord/ChatGPT-style UI: a chat box routes free-text user requests to one of several specialist agents, one of which — `video-agent` — is meant to be this project. His side already has a real, tested, hand-rolled A2A client (`backend/app/a2a_client.py`, `contracts.py`, `errors.py`, `registry.py`), hardened per his own spec (`docs/superpowers/specs/2026-08-07-a2a-contract-hardening-design.md`) and committed. Nobody designed the wire contract jointly — his code is the ground truth we build against, verified directly from his source and his own passing tests (`backend/tests/test_a2a_client.py`, `test_a2a_contract.py`), not the general A2A v0.3.0 spec.

Confirmed product decisions (from prior discussion, not re-litigated here):
- The A2A call triggers a full real render (all 7 pipeline stages + a real video render), not just planning.
- Default render backend is Veo (`VeoBackend`), not LTX or beat-split.
- Deployment/demo topology is same-machine `docker-compose`, with our container's port mapped to the host — his backend reaches us container-to-container (`http://video-agent:8002`), but a human's browser reaches us via a host-mapped port (`http://localhost:8002`).
- This spec targets the pipeline's *current* behavior, including its current all-or-nothing scene-failure behavior (one scene failing review kills the whole render). Making that partial/resumable is separate, already-identified follow-up work, deliberately deferred — not part of this spec.

## Goals

- Serve a correct Agent Card so his `AgentRegistry.refresh()` selects our HTTP+JSON 1.0 interface instead of falling back to synchronous-only legacy JSON-RPC (which cannot survive a multi-minute render).
- Accept a free-text Korean brief via `POST /message:send`, decide whether it's complete enough to render, and either ask a clarifying question synchronously or kick off a real async render task.
- Expose task status via `GET /tasks/{task_id}` in the exact shape his `A2AClient.poll_task` expects, verified against his own test fixtures.
- Deliver the finished video as a URL reachable from a browser on the demo machine, embedded in the task's final text answer (his frontend renders `answer` as plain text only — no media player).
- Surface errors (bad request, unknown task, pipeline failure) in his `A2AError`-compatible shape.

## Non-goals

- Partial-success / per-scene resumability (continuing when one scene fails review) — existing pipeline gap, tracked separately, not fixed here.
- A review/regenerate loop on the *rendered video clip* itself (only the keyframe image is reviewed today) — existing pipeline gap, not fixed here.
- Auth — `VIDEO_AGENT_TOKEN` is unset in his `.env.example` today; we accept unauthenticated requests but don't preclude adding Bearer-token verification later.
- Durable/cross-restart task storage (SQLite, Redis, a queue) — in-memory only, acceptable for a same-machine, single-run-at-a-time demo.
- Any change to the core pipeline package (`orchestrator.py`, `agents/`, `render_backends/`) — this server only calls it.

## Design

### Package layout

New package `src/video_draft_pipeline/a2a_server/`, kept fully separate from the core pipeline (which remains a plain callable library with no knowledge an A2A server exists):

- `app.py` — FastAPI app + route wiring
- `agent_card.py` — builds the `GET /.well-known/agent-card.json` response
- `brief_intake.py` — `BriefIntakeAgent` (regex hints + one Gemini structured call)
- `tasks.py` — in-memory task store
- `routes.py` — `POST /message:send`, `GET /tasks/{task_id}`, static `/media` mount
- `render_runner.py` — background job that drives `build_real_agents()` + `VeoBackend` + `run_pipeline(assemble=True)` and writes the result back into the task store

New dependencies: `fastapi`, `uvicorn` (runtime); `httpx` (dev-only, required by FastAPI's `TestClient`).

### Agent Card and the two base URLs

`GET /.well-known/agent-card.json` returns:

```json
{
  "name": "video-agent",
  "description": "게임 마케팅 영상 초안 생성 Agent",
  "url": "http://video-agent:8002/a2a",
  "skills": [{"id": "video_draft", "name": "영상 초안"}],
  "capabilities": {"streaming": false},
  "supportedInterfaces": [
    {"url": "http://video-agent:8002/message:send", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}
  ],
  "securitySchemes": {}
}
```

The `supportedInterfaces[0].url` is what makes `AgentRegistry.refresh()` overwrite `card.url` and route all future calls through our real async task path instead of legacy JSON-RPC — this is the load-bearing field.

Two different base URLs matter here and must not be conflated:
- **Internal URL** (`SELF_INTERNAL_URL`, default `http://video-agent:8002`) — used in the agent card's `supportedInterfaces` and matches his `VIDEO_AGENT_URL` default. His backend reaches us container-to-container using this; it is never seen by a browser.
- **Public media URL** (`MEDIA_PUBLIC_BASE_URL`, default `http://localhost:8002`) — used only when building the video URL embedded in a completed task's answer text, since that link is opened directly by a human's browser, not by his backend.

Both are env vars with the stated defaults, overridable for other topologies later without code changes.

### Request lifecycle

```
POST /message:send
  → extract raw text from message.parts
  → regex/keyword hint pass: duration ("N초"), budget (currency amount),
    preset/scene_type keywords (공개/이벤트/커뮤니티, 인게임/스튜디오)
  → BriefIntakeAgent(text, hints) → IntakeResult

  if IntakeResult.clarifying_question is set:
    respond 200 immediately:
      {"message": {"parts": [{"text": <Korean question>}]}}
    (his client reads this straight off message.parts → status "succeeded",
     no task created, no render cost — just the one intake call, ~$0.01-0.02)

  else (IntakeResult carries a usable brief):
    build ProjectInput (see "BriefIntakeAgent output → ProjectInput" below)
    task_id = new task; store state=TASK_STATE_WORKING
    schedule render_runner as a FastAPI background task
    respond 200 immediately:
      {"task": {"id": task_id, "status": {"state": "TASK_STATE_WORKING"}}}
    (no "url" in the task envelope — his client derives
     GET {base}/tasks/{task_id} itself from agent_url)

render_runner (background):
  agents = build_real_agents(output_dir="media/a2a_server", log_path=...)
  backend = VeoBackend(tier="veo-3.1-fast", output_dir="media/a2a_server")
  try:
      project = run_pipeline(project_input, render_backend=backend, assemble=True, **agents)
      # project.output_video_url is already "media/{project_id}.mp4" (orchestrator's default)
      url = f"{MEDIA_PUBLIC_BASE_URL}/{project.output_video_url}"
      store: state=TASK_STATE_COMPLETED,
             answer="<Korean 1-2 line summary>\n" + url
  except PipelineError as exc:
      store: state=TASK_STATE_FAILED, answer=f"영상 생성에 실패했습니다: {exc}"
  except Exception:
      log full traceback server-side
      store: state=TASK_STATE_FAILED, answer="영상 생성 중 알 수 없는 오류가 발생했습니다."

GET /tasks/{task_id}
  → 404 (NOT_FOUND) if unknown
  → {"task": {"id": task_id,
               "status": {"state": <state>,
                           "message": {"parts": [{"text": <answer>}]}}}}
```

`TASK_STATE_WORKING` for the non-terminal state and `TASK_STATE_COMPLETED`/`TASK_STATE_FAILED` for terminal states are taken directly from his own test fixtures (`test_a2a_contract.py`), not the general A2A spec — his `poll_task` only recognizes these exact strings (plus lowercase `completed`/`failed`/`cancelled`) as terminal.

### BriefIntakeAgent

Same shape as every other Gemini-backed agent in this codebase (`BaseGeminiAgent`, one `_structured_interaction()` call, a pydantic output model, `ESTIMATED_COST_USD`) — but lives in `a2a_server/`, not `agents/`, because it runs before a `ProjectInput` exists and is never part of `run_pipeline()`'s call graph.

Output model:

```python
class IntakeResult(BaseModel):
    brief: str | None = None
    preset: Preset | None = None
    scene_type: SceneType | None = None
    duration_sec: int | None = None
    max_budget_usd: float | None = None
    clarifying_question: str | None = None
```

Exactly one of `brief` or `clarifying_question` is set. The regex/keyword pre-pass extracts literal signals (a `N초` duration, a currency amount, known preset/scene_type keywords) and passes them as hints alongside the raw text — free pre-processing that makes the one LLM call cheaper and more accurate, not a second independent gate. The LLM remains the sole authority on confident-vs-vague.

**`IntakeResult` → `ProjectInput`:** `duration_sec` defaults to 10, `preset` to `"이벤트"`, `scene_type` to `"인게임"` when unset by the model (matching `scripts/gemini_pipeline_smoke_test.py`'s existing CLI defaults); `max_budget_usd` is only passed through if set, otherwise `ProjectInput`'s own default (5.00) applies.

### Task store

`tasks.py`: `dict[task_id, TaskRecord]` where `TaskRecord` holds `state`, `answer`, `created_at`. Process-lifetime only — a container restart mid-render loses that task, which is an accepted demo-scope limitation (see Non-goals).

### Media serving

`build_real_agents()`/`VeoBackend` write per-scene intermediate images/clips under `media/a2a_server/`; `run_pipeline()` is called with no explicit `assembly_output_path`, so the final assembled video lands at its existing default, `media/{project_id}.mp4` (`orchestrator.py`'s own convention). Rather than special-case the assembly path, `routes.py` mounts the whole top-level `media/` directory as a FastAPI `StaticFiles` route at `/media` — this covers both the intermediate subfolder and the final assembly with one mount, no path-juggling. The finished task's answer embeds `{MEDIA_PUBLIC_BASE_URL}/media/{project_id}.mp4`. This requires the teammate to map our container's port to the host in `docker-compose.yml` (e.g. `ports: ["8002:8002"]`) — a deployment note to hand him alongside the timeout/build-path checklist already identified.

### Error handling

Matches his fixed error contract exactly (`docs/superpowers/specs/2026-08-07-a2a-contract-hardening-design.md`: errors live in the `/message:send` response itself, no separate error endpoint), using his own status vocabulary so `A2AError.from_payload` needs no special-casing for us:

| Situation | status | HTTP |
|---|---|---|
| Malformed request (no `message.parts`, empty text) | `INVALID_ARGUMENT` | 400 |
| Unknown `task_id` on `GET /tasks/{id}` | `NOT_FOUND` | 404 |
| Missing Gemini/Veo API key at server startup | `UNAVAILABLE` | 503 |
| Pipeline failure during a background render | — | not an HTTP error; the *task* transitions to `TASK_STATE_FAILED` with a Korean `answer`, since the HTTP response already returned 200 with the task envelope before the render even started |
| Unexpected exception in the background job | — | same: task → `TASK_STATE_FAILED` with a generic Korean message; full traceback logged server-side only, never on the wire |

## Testing

- `tests/a2a_server/test_agent_card.py` — served JSON matches his `AgentCard`/`AgentInterface` field names exactly (`supportedInterfaces` alias, `protocolBinding`, `protocolVersion`).
- `tests/a2a_server/test_brief_intake.py` — `BriefIntakeAgent` against a stubbed Gemini client (same mocking pattern as existing agent tests): confident-brief branch, clarifying-question branch, regex hint extraction.
- `tests/a2a_server/test_message_send.py` / `test_tasks.py` — FastAPI `TestClient` integration tests for `/message:send` + `/tasks/{id}`, with a stub render pipeline (no real Gemini/Veo calls), asserting response shapes against his actual fixtures from `test_a2a_contract.py` (`TASK_STATE_WORKING`/`COMPLETED`/`FAILED`, `task.status.message.parts`).
- `scripts/a2a_server_smoke_test.py` (manual, not pytest, real billed calls) — starts the real server and drives a call through his actual `A2AClient`, not just our own routes; this is what validates the integration end-to-end rather than just our JSON shape in isolation.

## Open questions / follow-ups (not blocking this spec)

- Partial-success / per-scene resumability and manual-image-upload-to-finish-a-scene — separate future spec, sequenced after this one per the user's stated priority.
- Video-clip review/regeneration loop — existing pipeline gap, not addressed here.
- Auth (`VIDEO_AGENT_TOKEN`) — currently unset on his side; add Bearer-token verification here only if/when he sets one.
- Concrete checklist to hand the teammate (timeout/poll_timeout bump in his `A2AClient` construction, `docker-compose.yml` build path swap for `video-agent`, API key env vars, port mapping for `MEDIA_PUBLIC_BASE_URL` reachability) — not part of this spec's code, but needs relaying to him before this can actually be exercised end-to-end.
