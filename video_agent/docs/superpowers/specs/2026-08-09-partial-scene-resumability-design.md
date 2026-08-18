# Partial-scene resumability

## Context

Today, `run_pipeline` treats any scene that exhausts its retries without an accepted candidate as fatal: it raises `PipelineError` and the entire run is lost, even if the other 3 scenes in a 4-scene project passed review cleanly. This was hit for real during the 2026-08-08 A2A end-to-end test (`scene_04`, addressed separately by the shot-distance/prop-orientation review-leniency fix shipped 2026-08-09) and is a general robustness gap independent of that fix — some scene will eventually fail review for a reason no amount of prompt tuning solves, and today that means throwing away every other scene's work.

The desired behavior (per prior discussion): when a scene fails review after all retries, keep its last-generated image, skip rendering that scene's video clip, and let the rest of the pipeline finish. The images are saved either way, so a human can take the last failed image, fix it up externally (e.g. in Photoshop), and re-submit it to generate just that scene's video clip — without re-running or re-paying for the scenes that already passed.

## Goals

- A scene failing review after all retries no longer aborts the whole pipeline run; other scenes still get generated, reviewed, and rendered normally.
- The last failed candidate image for an unresolved scene is preserved and reachable (via the existing `/media` static mount).
- A human can submit a replacement image for a specific unresolved scene and have just that scene's video clip generated, without regenerating anything else.
- Once every scene in a project is resolved (either by passing review or by manual replacement), final assembly runs automatically.
- This works both as a local/CLI flow and through the A2A server, since the A2A server is the actual integration point with the teammate's Main Agent.

## Non-goals

- Not a video-clip review/regenerate loop (reviewing the rendered Veo/LTX output itself) — separate, already-identified follow-up, not touched here.
- Not extending the teammate's A2A `message:send` text-chat contract to carry file attachments — that's his client/protocol to extend, not ours. The resume flow is a plain REST endpoint alongside `message:send`, not part of the A2A message protocol.
- Not offering a "human approves every generated image" gate — that would defeat the point of the automated review/retry loop; this is strictly a fallback for when automation is exhausted.
- Not changing `GeminiReviewAgent`/`DirectorAgent` retry logic, `defect_category` classification, or the review-leniency prompt shipped earlier today.
- Not adding a way to *regenerate* a failed scene through the normal pipeline again (new prompt, new AI-generated candidate) — resume only accepts a human-supplied replacement image.

## Design

### Data model changes (`schema.py`)

- `Scene` gains `needs_manual_fix: bool = False`. Set `True` when a scene exhausts retries without an accepted candidate; cleared when the scene is resolved via manual resume.
- `Project` gains `running_cost_usd: float = 0.0`. Today the running cost is only a local variable inside `run_pipeline`; it must be persisted so a later, separate resume call (a different process or HTTP request) knows how much budget has already been spent and can still enforce `max_budget_usd`.

### Orchestrator behavior change (`orchestrator.py`)

Today, a scene's retry loop ending without an accepted candidate raises `PipelineError` via two separate code paths (the `for...else` on the retry loop, and the explicit `if scene.accepted_candidate_id is None` check after it). These collapse into one outcome:

- If the retry loop ends without `scene.accepted_candidate_id` being set, set `scene.needs_manual_fix = True`, leave the last (failed) candidate in `scene.candidates` as-is, **do not** run the video-render step for that scene (`scene.render` stays `None`), and continue to the next scene instead of raising.
- `PipelineError` is now reserved for genuinely fatal conditions only: budget exceeded, duration exceeded. A scene failing review is no longer one of them.
- After each scene resolves (accepted or `needs_manual_fix`), if a `project_store` was supplied, persist the project (see below). This bounds any crash/restart loss to at most the scene currently in flight.
- Final assembly (`assemble=True`) only runs if every scene in the project was accepted (no scene has `needs_manual_fix=True`). If any scene is unresolved, assembly is skipped entirely and `project.output_video_url` stays `None`.

Callers of `run_pipeline` can no longer assume "no exception raised" means "fully done" — they must check whether any scene has `needs_manual_fix=True`.

### Persistence (`project_store.py`, new)

- `ProjectStore(root_dir)`:
  - `save(project)` — writes `{root_dir}/{project.project_id}.json` via `project.model_dump_json()`.
  - `load(project_id)` — reads and parses the file back into a `Project`; raises `ProjectStoreError` if the file is missing or unparseable.
- `run_pipeline` gains an optional `project_store: ProjectStore | None = None` parameter. When provided, saves after each scene resolves. When `None` (the default), behavior is unchanged and nothing is written to disk — existing library/test callers are unaffected.

### Resume (`orchestrator.py`)

New function `resume_scene_with_image(project, scene_id, image_path, render_agent, project_store=None) -> Project`:

1. Find the scene by `scene_id`. Raise if it doesn't exist, or if `needs_manual_fix` is not `True` (nothing to resume).
2. Wrap the given image as a new `Candidate`: `generated_by="manual_upload"`, no `consistency_review`, a synthetic `director_decision=DirectorDecision(decision="accept", decided_by="human_manual_upload")`. Append it to `scene.candidates`, set `scene.accepted_candidate_id` to its id, clear `scene.needs_manual_fix`.
3. Run the video-render step for just this scene, charging its cost against `project.running_cost_usd` via the existing `budget_guard` (raises `PipelineError` on budget overrun, same as today, without mutating the project).
4. If every scene in the project is now resolved, run assembly and set `project.output_video_url`.
5. Persist via `project_store` if given. Return the updated `project`.

### CLI (`cli.py`)

- The main run command gains `--project-store-dir` (default `media/projects`) and always constructs a `ProjectStore` pointed there, passed into `run_pipeline`.
- After a run, if any scenes have `needs_manual_fix=True`, print each one's `scene_id` and last candidate's image path instead of only the final JSON dump, so the next step is obvious.
- New subcommand: `resume --project-store-dir DIR --project-id ID --scene-id ID --image PATH`. Loads the project via `ProjectStore.load`, calls `resume_scene_with_image`, saves, and prints the result — including the final video URL if that call completed assembly.

### A2A server

- `render_runner.default_render` passes a `ProjectStore` rooted at `media/a2a_server/projects` into `run_pipeline`.
- `tasks.TaskRecord` gains `project_id: str | None = None`, set by `run_render_task` once `run_pipeline` returns a `Project` (whether fully resolved or not) — this is what lets the resume endpoint map a `task_id` back to its project.
- `run_render_task` outcome messaging becomes three cases:
  - Fully resolved + assembled → `TASK_STATE_COMPLETED` with the video URL (unchanged from today).
  - Partially resolved (any scene `needs_manual_fix`) → `TASK_STATE_COMPLETED` (there's no better state in the teammate's fixed WORKING/COMPLETED/FAILED vocabulary) with a message listing each unresolved `scene_id`, its last failed image's `/media` URL, and the `task_id` needed for the resume call.
  - Fatal `PipelineError`/unexpected exception → `TASK_STATE_FAILED` (unchanged).
- New endpoint `POST /tasks/{task_id}/scenes/{scene_id}/resume`: multipart file upload carrying the replacement image. This is a plain REST endpoint alongside `message:send`, not an extension of the A2A text-chat protocol. Looks up the task's `project_id`, loads the project via `ProjectStore`, saves the uploaded file into the media directory, calls `resume_scene_with_image`, saves the project, and returns JSON directly to the caller (not via task polling): `{"scene_id", "resolved": true, "remaining_unresolved": [...], "output_video_url": "..." | null}` (`output_video_url` present only once every scene is resolved and assembly has run).

### Error handling

- Corrupt/unreadable uploaded image → surfaces as the render agent's existing error class, caught and returned as `UNAVAILABLE` at the endpoint level (same pattern as `message_send`'s existing error handling).
- Resuming an unknown `task_id`/`scene_id`, or a scene that isn't `needs_manual_fix` → `NOT_FOUND` / `INVALID_ARGUMENT` respectively, no partial mutation of the persisted project.
- Resuming a `task_id` whose `project_id` is still `None` (task never reached a point where a `Project` existed — e.g. it's still `TASK_STATE_WORKING`, or it failed before `run_pipeline` produced anything) → `NOT_FOUND`, same as an unknown task.
- Budget exceeded during resume → existing `BudgetExceededError` → `PipelineError` path; the project is not persisted mid-failure, so a retry of the resume call starts from the same known-good state.
- `ProjectStore.load` on a missing/corrupt file → `ProjectStoreError`, mapped to `NOT_FOUND` at the endpoint and to a clear error message on the CLI.

## Testing

- `orchestrator.py`: update existing tests that assert `PipelineError` on scene rejection to instead assert `needs_manual_fix=True`, no render, and that the pipeline continues to the next scene. Add tests for: all-scenes-unresolved → assembly skipped; one-scene-unresolved-others-accepted → assembly still skipped.
- New `test_project_store.py`: round-trip save/load; error on missing file.
- New tests for `resume_scene_with_image`: happy path (resolves the target scene only, others untouched); resolves-and-triggers-assembly when it's the last unresolved scene; error when the scene isn't `needs_manual_fix`.
- `test_cli.py`: new `resume` subcommand argument parsing, plus a happy-path test against a mocked orchestrator call.
- A2A server tests: extend `test_render_runner.py` for the partial-completion message case; new `test_resume_endpoint.py` covering the happy path and the `NOT_FOUND`/`INVALID_ARGUMENT` error cases.
- No live billed API calls anywhere in this test work — mocked agents/backends throughout, consistent with the rest of the suite.

## Open questions / follow-ups (not blocking this spec)

- Whether the teammate's Main Agent UI ever grows the ability to call the new resume endpoint (vs. it being operated manually/out-of-band for now) depends on his own roadmap — not something to build preemptively here.
- A video-clip review/regenerate loop (reviewing rendered Veo/LTX output, not just the keyframe image) remains a separate, deliberately out-of-scope follow-up.
