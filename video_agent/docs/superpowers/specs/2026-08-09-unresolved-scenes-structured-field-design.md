# Structured `unresolvedScenes` field for the A2A server

## Context

Partial-scene resumability (shipped 2026-08-09) lets a pipeline run finish with some scenes marked `needs_manual_fix`, and reports this through the A2A server's `GET /tasks/{task_id}` as `TASK_STATE_COMPLETED` with a Korean prose message listing the unresolved scenes, their last image URL, and how to resume them.

That message is fine for a human reading it directly, but there's no way for a program — specifically, the teammate's Main Agent frontend, if it ever grows an upload UI for this feature — to know which scenes need fixing without parsing prose. This spec adds a structured, machine-readable field alongside the existing message, and unifies it with the resume endpoint's existing (but currently string-only) `remaining_unresolved` list.

This was raised while discussing what it would take to build a front-end UI for resumability in the teammate's `AI-agent_game_platform` repo: his `A2AClient` parses task responses with plain `dict.get()` (confirmed in `backend/app/a2a_client.py`) and already uses camelCase for multi-word fields elsewhere in the same contract (`messageId`, `contextId`), so adding a new sibling field is both safe (no strict schema, extra fields are ignored) and should follow that same casing convention.

## Goals

- `GET /tasks/{task_id}` gains a structured `unresolvedScenes` array (only present when there are unresolved scenes) alongside the existing `state`/`message`.
- The resume endpoint's existing `remaining_unresolved` field upgrades its array elements from bare scene-id strings to the same per-scene object shape, so a future frontend can render "what's still broken" with one component regardless of which endpoint returned it.
- No extra `ProjectStore` disk read per `GET /tasks/{task_id}` poll — the data is computed once, when the task actually completes, and stored on the `TaskRecord`.

## Non-goals

- Not renaming any already-shipped field. `remaining_unresolved`'s own name, and the rest of the resume endpoint's response shape (`scene_id`, `resolved`, `output_video_url`), stay exactly as shipped in Task 7 — only the array's element shape changes.
- Not adding this to `message:send`'s synchronous response — that endpoint only ever returns a clarifying question or a freshly-created (`TASK_STATE_WORKING`) task; it never returns a completed task directly, so there's nothing to attach this to there.
- Not building any actual frontend or backend-proxy work in the teammate's `AI-agent_game_platform` repo — that's a separate, later effort on his side, not touched here.

## Design

### Per-scene entry shape

```json
{
  "sceneId": "scene_04",
  "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
  "issues": ["shot too wide", "prop held diagonally"]
}
```

- `sceneId` — `scene.scene_id`.
- `imageUrl` — `f"{media_public_base_url}/{scene.candidates[-1].image_url}"`, same construction already used by `_unresolved_scenes_message`.
- `issues` — `scene.candidates[-1].consistency_review.issues`, or `[]` if `consistency_review` is `None` (defensive only; in practice every candidate has gone through review before a scene can be marked `needs_manual_fix`).

Field names are camelCase, matching the teammate's existing contract convention (`messageId`, `contextId`) — this data rides inside `task.status`, which is part of that contract surface.

### `build_unresolved_scenes` helper (`a2a_server/render_runner.py`)

```python
def build_unresolved_scenes(project: Project, media_public_base_url: str) -> list[dict]:
    entries = []
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_candidate = scene.candidates[-1]
        review = last_candidate.consistency_review
        entries.append({
            "sceneId": scene.scene_id,
            "imageUrl": f"{media_public_base_url}/{last_candidate.image_url}",
            "issues": review.issues if review else [],
        })
    return entries
```

Co-located with the existing `_unresolved_scenes_message` (which iterates the same scenes for the prose message) — both stay in sync by construction since they're right next to each other, not because of any shared abstraction between prose and structured output (deliberately not merged into one function: one produces a Korean string, the other a JSON-serializable list, and forcing them through one code path would just add an if/else with no reuse benefit).

### `TaskRecord` / `TaskStore` (`a2a_server/tasks.py`)

- `TaskRecord` gains `unresolved_scenes: list[dict] | None = None`.
- New `TaskStore.set_unresolved_scenes(task_id: str, scenes: list[dict]) -> None`, mirroring the existing `set_project_id` method.

### `run_render_task` (`a2a_server/render_runner.py`)

In the partial-completion branch (`if any(scene.needs_manual_fix for scene in project.scenes):`), compute the list once and store it before marking the task completed:

```python
    if any(scene.needs_manual_fix for scene in project.scenes):
        unresolved = build_unresolved_scenes(project, media_public_base_url)
        task_store.set_unresolved_scenes(task_id, unresolved)
        task_store.mark_completed(task_id, _unresolved_scenes_message(project, media_public_base_url, task_id))
        return
```

### `GET /tasks/{task_id}` (`a2a_server/app.py`)

```python
    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        record = store.get(task_id)
        if record is None:
            return error_response("NOT_FOUND", f"Unknown task: {task_id}")
        status: dict = {"state": record.state}
        if record.answer is not None:
            status["message"] = {"parts": [{"text": record.answer}]}
        if record.unresolved_scenes:
            status["unresolvedScenes"] = record.unresolved_scenes
        return {"task": {"id": record.task_id, "status": status}}
```

`if record.unresolved_scenes` (not `is not None`) so an empty list is treated the same as absent — never emit `"unresolvedScenes": []`.

### Resume endpoint (`a2a_server/app.py`)

Replace the current `remaining = [s.scene_id for s in project.scenes if s.needs_manual_fix]` with:

```python
        remaining = build_unresolved_scenes(project, media_url)
```

(`media_url` is already in scope in this handler — same variable `default_render`/`run_render_task` call `media_public_base_url`.) Everything else in that response (`scene_id`, `resolved`, `output_video_url`) is unchanged.

## Testing

- `tests/a2a_server/test_render_runner.py`: extend the existing partial-completion test (`test_run_render_task_marks_completed_with_unresolved_scenes_message`) to also assert `store.get(task_id).unresolved_scenes == [{"sceneId": "scene_04", "imageUrl": "...", "issues": [...]}]` (or whatever the fixture's review issues are). New unit test for `build_unresolved_scenes` directly: a project with one `needs_manual_fix` scene and one resolved scene, asserting only the unresolved one appears, with correct field names and values.
- `tests/a2a_server/test_get_task_route.py`: new test asserting `GET /tasks/{task_id}` includes `unresolvedScenes` when the stored record has it, and a new test asserting the key is entirely absent (not an empty list) for a fully-resolved completed task.
- `tests/a2a_server/test_resume_endpoint.py`: update `test_resume_endpoint_leaves_other_unresolved_scenes_pending` (the one existing test whose assertion touches this field) to assert `remaining_unresolved == [{"sceneId": "scene_other", "imageUrl": "...", "issues": [...]}]` instead of `["scene_other"]`.
- No live billed API calls in any of this — same convention as the rest of the suite.

## Open questions / follow-ups (not blocking this spec)

- Whether/how the teammate's Main Agent ever consumes this field (a backend proxy route + frontend upload UI) is his repo's decision, not built here.
