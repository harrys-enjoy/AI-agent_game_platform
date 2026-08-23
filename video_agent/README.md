# video-draft-pipeline

Multi-agent video concept draft generator (발주용 영상 시안 자동 생성). Agents are deterministic stubs by default — the pipeline runs end-to-end without calling any model API unless real agents are explicitly injected (see below).

## What this is

Given a short brief (e.g. "할로윈 신규 캐릭터 공개 이벤트") plus a few production constraints (preset, scene type, duration, budget), this pipeline drafts a short marketing video concept end-to-end: it writes a narrative, storyboards it into scenes, generates a keyframe image per scene, reviews and retries images that don't hold up, renders each accepted keyframe into a real video clip, and (optionally) assembles the clips into one final `.mp4`. No human touches it between brief-in and video-out.

## How the pipeline works

`run_pipeline(ProjectInput)` runs seven agent stages in order:

1. **PlanningAgent** turns the brief into a `Narrative`: exactly 4 **beats** — `setup`, `conflict`, `climax`, `resolution` — the classic four-act shape, one per eventual scene. It also produces a single `StyleGuide` (`visual_style`, `color_palette`, `subject_blueprint`, and an optional `secondary_subject_blueprint` for a second recurring subject — a creature, vehicle, or antagonist — when the video has one) meant to be reused verbatim across every scene, so the "same" character/setting (and, when present, the "same" creature) doesn't visually drift beat to beat.
2. **StoryboardAgent** turns each beat into a `Scene` (camera/subject/action/setting), deterministically copying the `StyleGuide` onto every scene rather than trusting each independently-drafted scene to reword the same character consistently.
3. **PromptAgent** turns each scene into two English prompts: `image_prompt` (static composition — style/subject/action/setting/framing) and `video_motion_prompt` (camera/motion only). Tone follows the scene's beat: `climax` reads intense/dynamic/high-contrast, `setup` reads calm/wide/establishing.
4. **ImageAgent** generates a candidate keyframe image from `image_prompt`.
5. **ReviewAgent** checks the candidate against the style guide and prior candidates for consistency, classifying any defect (`localized_artifact` vs `structural_geometry`).
6. **DirectorAgent** decides `accept` / `regenerate` / `reject` from the review. On regenerate, the first retry is a targeted fix via `ImageEditAgent` (cheap); any further retry goes back through `PromptAgent` + `ImageAgent` for a fresh generation. A scene that never gets an accept fails the whole run rather than silently shipping a rejected frame.
7. **VideoRenderAgent** renders the accepted keyframe into a real video clip via a render backend — Veo 3.1 or LTX 2.3, either one for the whole video or split per beat (e.g. the higher-stakes `climax`/`resolution` beats through pricier Veo, `setup`/`conflict` through cheaper LTX — see `beat_backend_map`).
8. With `assemble=True`, all scene clips are concatenated in beat order (`ffmpeg`, hard cuts) into one final video at `Project.output_video_url`.

A budget guard checks every stage's cost against `max_budget_usd` as it goes (the run fails cleanly instead of overspending), and a duration guard checks the storyboard's total scene length against `max_duration_sec` before any generation starts.

## Current status / what's not built yet

The pipeline itself runs fully for real — all 7 Gemini-backed agent stages plus a real Veo or LTX render plus `ffmpeg` assembly — via the CLI or `scripts/gemini_pipeline_smoke_test.py`, validated with real billed API calls end-to-end.

An A2A (agent-to-agent) server exposing this pipeline as a callable agent for an outer orchestrator now exists — see "Running the A2A server" below. It's a single black-box entry point: an outer orchestrator hands off one free-text request and gets one result back, the same way `run_pipeline()` internally calls its own seven agents without any outside caller reaching into an individual stage.

**Not yet built:** a review/regenerate loop on the rendered video clip itself (only the keyframe image is reviewed today).

## Running the A2A server

`src/video_draft_pipeline/a2a_server/` exposes this pipeline as a callable A2A sub-agent:

**Standalone run (e.g. for manual testing or smoke test):**
```bash
SELF_INTERNAL_URL=http://localhost:8002 uvicorn video_draft_pipeline.a2a_server.app:app --host 0.0.0.0 --port 8002
```

**Docker:** a `Dockerfile` at the repo root builds and runs the server (installs `ffmpeg` for video assembly, installs the package from `pyproject.toml`, runs `uvicorn` on port 8002):
```bash
docker build -t video-agent .
docker run -p 8002:8002 -e GEMINI_API_KEY=... -e VEO_API_KEY=... -e VIDEO_SERVICE_TOKEN=... video-agent
```

**Docker-compose deployment:** omit the `SELF_INTERNAL_URL` override; the default `http://video-agent:8002` resolves within the container network and is advertised to calling orchestrators.

Environment variables:
- `SELF_INTERNAL_URL` (default `http://video-agent:8002`) — the URL advertised in the agent card's `supportedInterfaces`, reached container-to-container by a calling orchestrator. Override to `http://localhost:8002` for standalone runs where the agent card discovery and smoke test run from the same machine.
- `MEDIA_PUBLIC_BASE_URL` (default `http://localhost:8002`) — the URL used when building the finished video link in a completed task's answer, reached by a human's browser. These are deliberately different: the first only needs to resolve inside a Docker network, the second needs to resolve from wherever the video gets watched.
- `VIDEO_SERVICE_TOKEN` — the Bearer Service Token a calling orchestrator must send as `Authorization: Bearer {VIDEO_SERVICE_TOKEN}`, alongside an `A2A-Version: 1.0` header, on every `/a2a/*` request. Required for `/a2a/*` routes to accept any request — unset, every `/a2a/*` call gets a 401. Not read by the unprefixed `/tasks/{task_id}/scenes/{scene_id}/resume` or agent-card routes, which stay unauthenticated.

Endpoints (`/a2a/*` routes require `Authorization: Bearer {VIDEO_SERVICE_TOKEN}` + `A2A-Version: 1.0`; the rest don't):
- `GET /.well-known/agent-card.json` — unauthenticated
- `POST /a2a/message:send` — authenticated. Send an optional `X-Video-Agent-User` header to tag the created task with an owner (URL-encoded); the same value is later used to filter `GET /a2a/tasks`. `messageId` is de-duplicated server-side (`claim_message_id`) — resending the same `messageId` returns the already-created task instead of starting a second render.
- `GET /a2a/tasks/{task_id}` — authenticated
- `GET /a2a/tasks?user_id=...&limit=20&offset=0` — authenticated. Lists tasks for one owner (paginated, `has_more` in the response), backing the video gallery view.
- `GET /a2a/tasks/{task_id}/detail` — authenticated. Returns the full generation record (narrative/storyboard/prompts, not just task status) by loading the linked project from `ProjectStore` — used for a gallery thumbnail's "view details" panel.
- `DELETE /a2a/tasks/{task_id}` — authenticated. Deletes the task record, its output video file, and its stored project JSON. Refuses tasks still `SUBMITTED`/`WORKING` — cancel first, then delete.
- `GET /a2a/veo-usage` — authenticated. Returns `{used, limit, resetsAt}` from the local Veo call counter (`veo_usage_repository.py`) — a per-instance, 24h-rolling count, not Google's actual account-level quota (see that module's docstring).
- `POST /a2a/tasks/{task_id}:cancel` — authenticated
- `GET /media/{filename}` — unauthenticated
- `POST /tasks/{task_id}/scenes/{scene_id}/resume` — unauthenticated

### Resuming a scene that needs a manual fix

If a scene exhausts its retries without passing review, the run doesn't abort — that scene is skipped (no video render, no assembly) and the rest of the project finishes normally. The task moves to `TASK_STATE_INPUT_REQUIRED`, whose message lists which scenes need a fix and a link to each one's last generated image. Additionally, `GET /a2a/tasks/{task_id}` returns a structured `status.unresolvedScenes` array (present only when scenes are unresolved; the key is omitted entirely when all scenes are resolved), with each entry as `{"sceneId": "...", "imageUrl": "...", "issues": [...], "referenceImageUrl": "..."}` (`referenceImageUrl` is `string | null` — present when a project-level consistency anchor exists, `null` otherwise).

To resume: fix the image externally (e.g. Photoshop) and `POST` it as multipart form data:

```bash
curl -X POST http://localhost:8002/tasks/<task_id>/scenes/<scene_id>/resume \
  -F "file=@fixed_scene.png"
```

The response includes `remaining_unresolved` (any other scenes still needing a fix, as an array of `{sceneId, imageUrl, issues, referenceImageUrl}` objects) and `output_video_url` (set only once every scene is resolved and final assembly has run). This is a plain REST endpoint, not part of the A2A `message:send` text-chat contract — the teammate's `A2AClient` doesn't call it.

If the server has restarted since the original task completed, the in-memory task record is gone and `<task_id>` no longer resolves — substitute the project's own `project_id` (visible in the project JSON, e.g. via the CLI's `resume` output or the stored project file) for `task_id` in the resume URL instead.

The same resume flow is available without the server, via the CLI: `python -m video_draft_pipeline.cli resume --project-store-dir <dir> --project-id <id> --scene-id <id> --image <path>`.

See `docs/superpowers/specs/2026-08-08-a2a-server-design.md` for the full design, and `scripts/a2a_server_smoke_test.py` for a real end-to-end call against a running server.

**For the calling orchestrator's integration** (verified against `AI-agent_game_platform`'s actual `A2AClient`): its default `A2AClient(timeout=5.0, poll_timeout=30.0)` is far too short for a multi-minute render — bump both at every construction site in its `backend/app/main.py`. Its `docker-compose.yml`'s `video-agent` service still builds from `./mock-agents`; point its `build:` at this repo's root (where the `Dockerfile` above lives) instead. And its `VIDEO_AGENT_URL`'s port must be mapped to the host (e.g. `ports: ["8002:8002"]`) for `MEDIA_PUBLIC_BASE_URL` links to be reachable from a browser.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.11+. The optional video-assembly step (`assemble=True`) additionally requires `ffmpeg` installed and on `PATH` — not needed for anything else.

## Run

```bash
python -m video_draft_pipeline.cli \
  --preset 이벤트 \
  --scene-type 인게임 \
  --duration 30 \
  --brief "Halloween Event" \
  --max-budget 5.00
```

| Flag | Required | Values |
| --- | --- | --- |
| `--preset` | yes | `공개`, `이벤트`, `커뮤니티` |
| `--scene-type` | yes | `인게임`, `스튜디오` |
| `--duration` | yes | seconds, 1–30 |
| `--brief` | yes | free text |
| `--max-budget` | no | USD, must be > 0 (default `5.00`) |
| `--project-store-dir` | no | directory to persist each run's project JSON (default `media/projects`) |

The project JSON is printed to stdout. Invalid input or a pipeline failure (duration cap, budget cap) prints a one-line message to stderr and exits `1`; malformed flags exit `2` via argparse. A scene that exhausts its retries without passing review no longer aborts the run: the pipeline still completes normally (exit `0`), the full project JSON still prints to stdout, and a multi-line warning prints to stderr listing each unresolved scene, its last generated image, and the exact command to resume it. See "Resuming a scene that needs a manual fix" above (in the A2A server section) — the same resume flow is also available via `python -m video_draft_pipeline.cli resume`, as printed in the warning.

## Environment variables

`.env` is **not** auto-loaded — there is no `python-dotenv` dependency. `config.load_api_keys()` reads `os.environ` directly, so export the keys into your shell before running:

```bash
export GEMINI_API_KEY=...      # PowerShell: $env:GEMINI_API_KEY = "..."
export VEO_API_KEY=...
export LTX_API_KEY=...
```

**Avoid typing real keys into a terminal a chat assistant can see, or pasting `$env:`/`export` output back into one — that puts the literal key into the conversation transcript.** As a safer alternative, `config.load_api_keys()` also falls back to `~/.gemini_api_key`, `~/.veo_api_key`, `~/.ltx_api_key` (plain text, just the key on one line) if the matching env var isn't set. Create these by hand in your own editor, outside any terminal or chat.

All seven agent stages (`planning`, `storyboard`, `prompt`, `image`, `image_edit`, `review`, `director`) call Gemini directly with your own `GEMINI_API_KEY` — there is no Elice proxy on this branch. Veo 3.1 and LTX remain the exception: they're accessed directly against their own APIs and billed out of pocket, so `VEO_API_KEY` and `LTX_API_KEY` stay separate, real API keys (LTX isn't in Elice's catalog at all).

`.env.example` lists the key names as a reference.

## Model configuration

`config.ModelConfig` holds the model name per agent and the default render backend tier. `run_pipeline` accepts a `ModelConfig` and threads it into each stub agent constructor it builds by default:

```python
from video_draft_pipeline.config import ModelConfig
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, model_config=ModelConfig(render_backend="veo-3.1-lite"))
```

An explicit `render_backend=` argument to `run_pipeline` overrides `ModelConfig.render_backend`.

## Real agent injection

**Branch note:** on `gemini-unification`, every agent (`planning`, `storyboard`, `prompt`, `image`, `image_edit`, `review`, `director`) calls Gemini directly with `GEMINI_API_KEY` — no Elice proxy. This differs from `master`, where 5 of the 7 stages route through Elice's OpenAI-compatible gateway. See `docs/superpowers/specs/2026-08-03-gemini-unification-design.md` for why.

`run_pipeline` accepts `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, `image_edit_agent`, `review_agent`, `director_agent`, and `render_backend` — pass an instance of the matching real class to use it for that stage instead of the stub. Any not given fall back to their stub, so the pipeline stays fully offline by default. For `render_backend` the stub is `StubRenderBackend` and the real class is `VeoBackend`; inject it the same way as the others: `render_backend=VeoBackend(tier=..., api_key="...")`.

For finer control than one backend for the whole video, `run_pipeline` also accepts `render_backend_by_beat: dict[BeatId, RenderBackend]`, letting different narrative beats render through different backends — a scene's `beat_id` (`setup`/`conflict`/`climax`/`resolution`) picks which backend it uses, falling back to `render_backend` for any beat not in the map. `agents.video_render_agent.beat_backend_map(paid_backend, free_backend)` builds the recommended split (`climax`/`resolution` → `paid_backend`, `setup`/`conflict` → `free_backend`):

```python
from video_draft_pipeline.agents.video_render_agent import beat_backend_map

run_pipeline(
    project_input,
    render_backend_by_beat=beat_backend_map(
        paid_backend=VeoBackend(tier="veo-3.1-standard", api_key="..."),
        free_backend=LTXBackend(api_key="..."),
    ),
)
```

`LTXBackend` (`video_draft_pipeline.render_backends.ltx_backend`) is a real render backend calling LTX's `image-to-video` API directly (not through Elice — `LTX_API_KEY` is a separate, real key, billed out of pocket like `VEO_API_KEY`). It generates audio bundled with the video by default. Despite `beat_backend_map`'s `free_backend` parameter name, `LTXBackend` is not actually free — it's just the cheaper of the two real backends (`ltx-2-3-fast` at `$0.06`/sec by default vs. Veo's tiers), a naming holdover from when this parameter's real argument was still a stub.

On a director rejection, the first retry edits the rejected image via `image_edit_agent` (targeted, cheap); the second and any further retries revise the scene's prompts via `prompt_agent` and regenerate from scratch via `image_agent`. If you inject a real `image_agent` (or `prompt_agent`) but leave `image_edit_agent` on its stub default, the first retry of any rejected scene silently produces a fake `stub://gemini-2.5-flash-image/...` candidate that flows through review → director → render → assembly exactly like a real one, reporting `status="done"` with no error. Inject `image_edit_agent` alongside `image_agent` if you want retries to be real.

The easiest way to inject all seven at once is `build_real_agents()`, which constructs them with shared config and returns a dict shaped exactly for `run_pipeline`'s injection parameters:

```python
from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, **build_real_agents(gemini_api_key="..."))
```

`build_real_agents` takes its own `model_config: ModelConfig` argument — it builds all 7 real agents from `ModelConfig()` defaults unless you pass one in. If you also want non-default models, pass the *same* `ModelConfig` to both `build_real_agents` and `run_pipeline`, or the two calls won't share model choices and some stages will silently use the wrong model:

```python
from video_draft_pipeline.config import ModelConfig

cfg = ModelConfig(planning_model="gemini-3.1-pro-preview", render_backend="veo-3.1-lite")
run_pipeline(
    project_input,
    model_config=cfg,
    **build_real_agents(gemini_api_key="...", model_config=cfg),
)
```

To inject just one or two stages instead of all seven, construct that agent directly — all 7 are Gemini-backed, each under its own `video_draft_pipeline.agents.gemini_*_agent` module (`gemini_planning_agent`, `gemini_storyboard_agent`, `gemini_prompt_agent`, `gemini_image_agent`, `gemini_image_edit_agent`, `gemini_review_agent`, `gemini_director_agent`):

```python
from video_draft_pipeline.agents.gemini_planning_agent import GeminiPlanningAgent
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, planning_agent=GeminiPlanningAgent(api_key="..."))
```

An injected real agent's own `model_name` applies for that stage — `ModelConfig`'s corresponding field on `run_pipeline` is bypassed for any stage you inject (via either path above). `GeminiImageEditAgent` (like `GeminiReviewAgent`) reads the candidate's `image_url` as a real file path, so it only works when paired with a real `image_agent` that actually writes files (not the stub, which produces `stub://...` URLs).

### Global style consistency across scenes

Because `prompt_agent` and `image_agent` each run once per scene with no visibility into other scenes' calls, nothing used to stop the 4 generated images from looking like 4 unrelated pictures — a different-looking "same" character, a different art style, different color grading per shot. `planning_agent` now also produces a `StyleGuide` (`Narrative.style_guide`: `visual_style`, `color_palette`, `subject_blueprint`) alongside the 4 beats. `storyboard_agent` deterministically copies `subject_blueprint`/`visual_style`/`color_palette` onto **every** scene's `Storyboard` — it does not trust the LLM to reword the same character consistently on each independently-drafted scene; the anchor text is reused verbatim (falling back to the storyboard LLM's own per-scene guess only if no blueprint is present, e.g. a stub `Narrative`). `prompt_agent` then translates that anchor into English once per scene, explicitly instructed to keep it consistent with "how the same character/style would be described in any other scene of this project."

The same mechanism now covers a **second** recurring subject via `StyleGuide.secondary_subject_blueprint` (e.g. a monster, creature, or vehicle that appears across multiple scenes but isn't the main character). `planning_agent` only fills it in when the brief actually implies a second recurring subject, otherwise it's left empty; `storyboard_agent` copies it onto every scene the same way as `subject_blueprint`, and `prompt_agent` is explicitly told not to invent a second recurring character on its own when it's empty. This closed a real bug: without a shared blueprint, an independently-drafted "creature" in each scene rendered with a different eye shape, body shape, and color per scene, since nothing anchored the description across the 4 independent `prompt_agent`/`image_agent` calls.

`prompt_agent` also now factors in `scene.beat_id` for tone (a `climax` scene reads as "intense, dynamic, high-contrast," a `setup` scene as "calm, wide, establishing"), enforces separate prompt formulas for `image_prompt` (static: style/subject/action/setting/framing, no camera-movement verbs) vs. `video_motion_prompt` (motion/camera only, no repeated static detail), and forces English output for both regardless of the Korean scene input — image and video diffusion models handle English prompts far more reliably. `required_elements` (from `ProjectInput.brand_requirements`) still get deterministically string-appended after the LLM call rather than trusted to survive inside the generated text, since those are the client's actual commissioned requirements, not a nice-to-have.

### Inspecting agent input/output

Every real Gemini agent (all 7 stages) accepts `log_path: str | Path | None = None`, either directly or threaded through `build_real_agents(log_path=...)`. When set, each call appends one JSON line to that file: timestamp, agent class, model, the input sent to Gemini, and the parsed output — e.g. what `prompt_agent` generated and what `image_agent` received, in order, across a whole run. Image bytes inside `input` are replaced with a `<N base64 chars omitted>` placeholder so the file stays small and readable; a raw `output_image` is never logged, only the resulting `candidate_id`/`image_path`. This is local file I/O — it costs no API tokens and is off by default (`log_path=None`). `scripts/gemini_pipeline_smoke_test.py` enables it by default at `media/gemini_pipeline_smoke_test/agent_log.jsonl` (`--no-log` to disable, `--log-path` to redirect). No external tool (LangSmith, Langfuse, etc.) is needed to read it — it's plain JSONL, greppable or loadable with `json.loads` per line.

## Video assembly

`run_pipeline` accepts `assemble: bool = False` and `assembly_output_path: str | Path | None = None`. When `assemble=True`, after all scenes are rendered, their clips are concatenated in order (via `ffmpeg`'s concat demuxer, a hard cut between clips — no crossfades) into one final video, and `Project.output_video_url` is set to the result. Off by default, so a stub/offline `run_pipeline()` call never touches `ffmpeg`:

```python
run_pipeline(project_input, assemble=True)
# or with an explicit output path:
run_pipeline(project_input, assemble=True, assembly_output_path="media/my-final-cut.mp4")
```

Without `assembly_output_path`, the output defaults to `media/<project_id>.mp4`.

**Requires `ffmpeg` installed and on `PATH`** — this is a system binary, not a Python dependency, so it isn't installed by `pip install`. If any scene's render backend is still the stub `StubRenderBackend`, its `clip_url` is a fake `stub://...` path, not a real file — assembling those will fail; inject a real render backend (e.g. `VeoBackend`, `LTXBackend`) for real output.

## Test

```bash
pytest -v
```
