# Structured `unresolvedScenes` Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured, machine-readable `unresolvedScenes` list to the A2A server's `GET /tasks/{task_id}` response and unify the resume endpoint's existing `remaining_unresolved` field to use the same per-scene object shape.

**Architecture:** A new shared helper `build_unresolved_scenes(project, media_public_base_url)` (co-located with the existing `_unresolved_scenes_message` in `render_runner.py`) builds a list of `{sceneId, imageUrl, issues}` dicts. `run_render_task` calls it once, when a run completes with unresolved scenes, and stores the result on the `TaskRecord` via a new `TaskStore.set_unresolved_scenes` method — so `GET /tasks/{task_id}` just echoes a stored value with no extra disk I/O per poll. The resume endpoint calls the same helper directly on the `Project` object it already holds in memory.

**Tech Stack:** Python 3.11, FastAPI, pytest — same stack and conventions as the rest of `video_draft_pipeline`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-unresolved-scenes-structured-field-design.md`.
- New per-scene field names are camelCase (`sceneId`, `imageUrl`, `issues`) — matches the teammate's existing A2A contract convention (`messageId`, `contextId`).
- No already-shipped field is renamed: `remaining_unresolved`'s own name, and `scene_id`/`resolved`/`output_video_url` in the resume endpoint's response, stay exactly as they are today — only `remaining_unresolved`'s array elements change from bare strings to objects.
- `GET /tasks/{task_id}` never emits `"unresolvedScenes": []` — the key is entirely absent when there's nothing unresolved (`if record.unresolved_scenes`, not `is not None`).
- No live billed Gemini/Veo/LTX API calls in any test — same convention as the rest of the suite.

---

### Task 1: `build_unresolved_scenes` helper, `TaskStore` storage, and wiring into both endpoints

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/tasks.py`
- Modify: `src/video_draft_pipeline/a2a_server/render_runner.py`
- Modify: `src/video_draft_pipeline/a2a_server/app.py`
- Modify: `tests/a2a_server/test_tasks.py`
- Modify: `tests/a2a_server/test_render_runner.py`
- Modify: `tests/a2a_server/test_get_task_route.py`
- Modify: `tests/a2a_server/test_resume_endpoint.py`

**Interfaces:**
- Produces: `TaskRecord.unresolved_scenes: list[dict] | None` (default `None`); `TaskStore.set_unresolved_scenes(task_id: str, scenes: list[dict]) -> None`; `render_runner.build_unresolved_scenes(project: Project, media_public_base_url: str) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

In `tests/a2a_server/test_tasks.py`, add at the end of the file:

```python
def test_set_unresolved_scenes_updates_record():
    store = TaskStore()
    record = store.create()
    scenes = [{"sceneId": "scene_04", "imageUrl": "http://x/cand_1.png", "issues": ["too wide"]}]

    store.set_unresolved_scenes(record.task_id, scenes)

    assert store.get(record.task_id).unresolved_scenes == scenes


def test_create_returns_record_with_unresolved_scenes_none():
    store = TaskStore()

    record = store.create()

    assert record.unresolved_scenes is None
```

In `tests/a2a_server/test_render_runner.py`, change the import line:

```python
from video_draft_pipeline.a2a_server.render_runner import build_unresolved_scenes, run_render_task
```

and change the schema import line to add `ConsistencyReview`:

```python
from video_draft_pipeline.schema import Candidate, ConsistencyReview, Project, ProjectInput, Prompts, Scene, Storyboard
```

Add at the end of the file:

```python
def test_build_unresolved_scenes_returns_only_unresolved_with_issues():
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    resolved_review = ConsistencyReview(reviewed_by="r", passed=True, issues=[])
    unresolved_review = ConsistencyReview(reviewed_by="r", passed=False, issues=["shot too wide", "prop diagonal"])
    ok_scene = Scene(
        scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard,
        accepted_candidate_id="cand_ok",
        candidates=[
            Candidate(
                candidate_id="cand_ok", image_url="media/cand_ok.png", generated_by="m",
                consistency_review=resolved_review,
            )
        ],
    )
    bad_scene = Scene(
        scene_id="scene_04", beat_id="resolution", order=4, duration_sec=5,
        storyboard=storyboard,
        needs_manual_fix=True,
        candidates=[
            Candidate(
                candidate_id="cand_1", image_url="media/a2a_server/cand_1.png", generated_by="m",
                consistency_review=unresolved_review,
            )
        ],
    )
    project = Project(project_id="proj_partial", input=_project_input())
    project.scenes = [ok_scene, bad_scene]

    result = build_unresolved_scenes(project, "http://localhost:8002")

    assert result == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": ["shot too wide", "prop diagonal"],
        }
    ]
```

Then extend the existing `test_run_render_task_marks_completed_with_unresolved_scenes_message` test (do not remove its existing assertions) by appending this line at the end of the function body:

```python
    assert updated.unresolved_scenes == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": [],
        }
    ]
```

In `tests/a2a_server/test_get_task_route.py`, add at the end of the file:

```python
def test_get_task_includes_unresolved_scenes_when_present(tmp_path):
    store = TaskStore()
    record = store.create()
    store.mark_completed(record.task_id, "일부 장면에 수동 수정이 필요합니다")
    store.set_unresolved_scenes(
        record.task_id,
        [{"sceneId": "scene_04", "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png", "issues": ["too wide"]}],
    )
    app = create_app(task_store=store, media_dir=str(tmp_path))
    client = TestClient(app)

    response = client.get(f"/tasks/{record.task_id}")

    body = response.json()
    assert body["task"]["status"]["unresolvedScenes"] == [
        {"sceneId": "scene_04", "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png", "issues": ["too wide"]}
    ]


def test_get_task_omits_unresolved_scenes_key_when_fully_resolved(tmp_path):
    store = TaskStore()
    record = store.create()
    store.mark_completed(record.task_id, "영상이 완성되었습니다.\nhttp://localhost:8002/media/proj_x.mp4")
    app = create_app(task_store=store, media_dir=str(tmp_path))
    client = TestClient(app)

    response = client.get(f"/tasks/{record.task_id}")

    body = response.json()
    assert "unresolvedScenes" not in body["task"]["status"]
```

In `tests/a2a_server/test_resume_endpoint.py`, update `test_resume_endpoint_leaves_other_unresolved_scenes_pending`'s assertion — replace:

```python
    assert body["remaining_unresolved"] == ["scene_other"]
```

with:

```python
    assert body["remaining_unresolved"] == [
        {"sceneId": "scene_other", "imageUrl": "http://localhost:8002/stub://bad2.png", "issues": []}
    ]
```

(No other change needed in this file — `other_scene`'s candidate at `stub://bad2.png` has no `consistency_review`, so `issues` is `[]`; `media_url` defaults to `http://localhost:8002` in `_setup_app`, matching every other assertion already in this file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server -v`
Expected: FAIL — `AttributeError: 'TaskStore' object has no attribute 'set_unresolved_scenes'`, `ImportError: cannot import name 'build_unresolved_scenes'`, `AssertionError` on the updated `remaining_unresolved` shape, and `KeyError`/`AssertionError` on `unresolvedScenes` in the two new `test_get_task_route.py` tests.

- [ ] **Step 3: Implement**

In `src/video_draft_pipeline/a2a_server/tasks.py`, replace the file contents:

```python
import uuid
from dataclasses import dataclass


@dataclass
class TaskRecord:
    task_id: str
    state: str = "TASK_STATE_WORKING"
    answer: str | None = None
    project_id: str | None = None
    unresolved_scenes: list[dict] | None = None


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}

    def create(self) -> TaskRecord:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        record = TaskRecord(task_id=task_id)
        self._tasks[task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def mark_completed(self, task_id: str, answer: str) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_COMPLETED"
        record.answer = answer

    def mark_failed(self, task_id: str, answer: str) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_FAILED"
        record.answer = answer

    def set_project_id(self, task_id: str, project_id: str) -> None:
        self._tasks[task_id].project_id = project_id

    def set_unresolved_scenes(self, task_id: str, scenes: list[dict]) -> None:
        self._tasks[task_id].unresolved_scenes = scenes
```

In `src/video_draft_pipeline/a2a_server/render_runner.py`, add this function directly after `_unresolved_scenes_message` (before `run_render_task`):

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

Then change `run_render_task`'s partial-completion branch from:

```python
    if any(scene.needs_manual_fix for scene in project.scenes):
        task_store.mark_completed(task_id, _unresolved_scenes_message(project, media_public_base_url, task_id))
        return
```

to:

```python
    if any(scene.needs_manual_fix for scene in project.scenes):
        unresolved = build_unresolved_scenes(project, media_public_base_url)
        task_store.set_unresolved_scenes(task_id, unresolved)
        task_store.mark_completed(task_id, _unresolved_scenes_message(project, media_public_base_url, task_id))
        return
```

In `src/video_draft_pipeline/a2a_server/app.py`, change the render_runner import line from:

```python
from .render_runner import default_render, default_resume_render_agent, run_render_task
```

to:

```python
from .render_runner import build_unresolved_scenes, default_render, default_resume_render_agent, run_render_task
```

Change the `get_task` route from:

```python
    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        record = store.get(task_id)
        if record is None:
            return error_response("NOT_FOUND", f"Unknown task: {task_id}")
        status: dict = {"state": record.state}
        if record.answer is not None:
            status["message"] = {"parts": [{"text": record.answer}]}
        return {"task": {"id": record.task_id, "status": status}}
```

to:

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

In the `resume_scene` route, change:

```python
        remaining = [s.scene_id for s in project.scenes if s.needs_manual_fix]
```

to:

```python
        remaining = build_unresolved_scenes(project, media_url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server -v`
Expected: PASS — full `a2a_server` test suite.

- [ ] **Step 5: Run the entire suite**

Run: `pytest -v`
Expected: PASS — every test in the repo.

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/tasks.py src/video_draft_pipeline/a2a_server/render_runner.py src/video_draft_pipeline/a2a_server/app.py tests/a2a_server/test_tasks.py tests/a2a_server/test_render_runner.py tests/a2a_server/test_get_task_route.py tests/a2a_server/test_resume_endpoint.py
git commit -m "feat: add structured unresolvedScenes field to A2A task status and resume response"
```
