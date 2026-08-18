# Partial-Scene Resumability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a scene exhausts its retries without passing review, keep the pipeline moving (skip only that scene's video render) instead of aborting the whole run, persist enough state that a human can later submit a replacement image for just that scene, and expose that resume flow through the CLI and the A2A server.

**Architecture:** `orchestrator.run_pipeline` changes from "any unresolved scene raises `PipelineError`" to "an unresolved scene sets `Scene.needs_manual_fix=True`, keeps its last candidate, skips its render, and the run continues" — final assembly is gated on every scene being resolved. A new file-backed `ProjectStore` persists `Project` state after each scene resolves, making it loadable from a separate later process. A new `resume_scene_with_image` orchestrator function accepts a replacement image for one `needs_manual_fix` scene, renders just that scene, and re-checks whether assembly can now run. The CLI gets a `resume` subcommand; the A2A server gets a `POST /tasks/{task_id}/scenes/{scene_id}/resume` REST endpoint (deliberately outside the teammate's `message:send` text-chat contract, which cannot carry file attachments).

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI/Starlette (multipart `UploadFile`), pytest, existing `video_draft_pipeline` package conventions.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-partial-scene-resumability-design.md`.
- `run_pipeline()` called with no `project_store` argument must behave exactly as before this plan except for the scene-failure semantics change — no new disk writes, no new required dependency, stays fully offline/stub-safe (see `README.md`'s offline-by-default section and `tests/test_orchestrator.py::test_run_pipeline_works_offline_with_no_api_keys_set`).
- `PipelineError` is reserved for genuinely fatal conditions only (budget exceeded, duration exceeded, assembly/ffmpeg failure). A scene exhausting retries without an accepted candidate must never raise it.
- No live billed Gemini/Veo/LTX API calls in any test in this plan — every agent/backend is a fake, stub, or mock, matching the rest of the suite.
- The teammate's A2A task terminal-state vocabulary is fixed and verbatim: `TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`. The new resume endpoint is a plain REST endpoint alongside `message:send`, not a new task state and not part of the A2A message protocol.
- New a2a_server error responses must use the existing `error_response(status, message)` helper (`src/video_draft_pipeline/a2a_server/errors.py`) with `STATUS_HTTP_CODES` (`INVALID_ARGUMENT`, `NOT_FOUND`, `UNAVAILABLE`).

---

### Task 1: Schema changes — `needs_manual_fix` and `running_cost_usd`

**Files:**
- Modify: `src/video_draft_pipeline/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `Scene.needs_manual_fix: bool` (default `False`), `Project.running_cost_usd: float` (default `0.0`). Every later task in this plan reads/writes these two fields by exactly these names.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_schema.py`, directly after `test_scene_rejects_wrong_type_on_assignment` (uses the existing `_scene()` helper already defined in that file):

```python
def test_scene_needs_manual_fix_defaults_to_false():
    scene = _scene()
    assert scene.needs_manual_fix is False
```

Add directly after `test_project_assembles_full_tree`:

```python
def test_project_running_cost_usd_defaults_to_zero():
    pi = ProjectInput(preset="공개", scene_type="스튜디오", duration_sec=30, brief="Reveal")
    project = Project(project_id="proj_1", input=pi)
    assert project.running_cost_usd == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schema.py -k "needs_manual_fix or running_cost_usd" -v`
Expected: FAIL — `AttributeError: 'Scene' object has no attribute 'needs_manual_fix'` and the equivalent for `Project.running_cost_usd`.

- [ ] **Step 3: Add the fields**

In `src/video_draft_pipeline/schema.py`, in the `Scene` class, add a new field directly after `accepted_candidate_id: str | None = None`:

```python
    needs_manual_fix: bool = False
```

In the `Project` class, add a new field directly after `output_video_url: str | None = None`:

```python
    running_cost_usd: float = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (all tests in the file, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/schema.py tests/test_schema.py
git commit -m "feat: add Scene.needs_manual_fix and Project.running_cost_usd fields"
```

---

### Task 2: `ProjectStore` — file-backed Project persistence

**Files:**
- Create: `src/video_draft_pipeline/project_store.py`
- Test: `tests/test_project_store.py`

**Interfaces:**
- Consumes: `Project` (from `schema.py`, Task 1's fields already present).
- Produces: `ProjectStore(root_dir: str | Path)` with `.save(project: Project) -> None` and `.load(project_id: str) -> Project`; `ProjectStoreError(Exception)`. Tasks 3, 4, 5, 6, 7 all construct and use this exact class.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_project_store.py`:

```python
import pytest

from video_draft_pipeline.project_store import ProjectStore, ProjectStoreError
from video_draft_pipeline.schema import Project, ProjectInput


def _project() -> Project:
    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event")
    return Project(project_id="proj_store_test", input=project_input, running_cost_usd=1.23)


def test_save_then_load_round_trips_project(tmp_path):
    store = ProjectStore(tmp_path)
    project = _project()

    store.save(project)
    loaded = store.load("proj_store_test")

    assert loaded.project_id == "proj_store_test"
    assert loaded.running_cost_usd == 1.23
    assert loaded.input.brief == "Halloween Event"


def test_load_raises_when_project_id_unknown(tmp_path):
    store = ProjectStore(tmp_path)

    with pytest.raises(ProjectStoreError):
        store.load("does-not-exist")


def test_load_raises_when_file_is_corrupt(tmp_path):
    store = ProjectStore(tmp_path)
    (tmp_path / "corrupt.json").write_text("not valid json{{{", encoding="utf-8")

    with pytest.raises(ProjectStoreError):
        store.load("corrupt")


def test_save_creates_root_dir_if_missing(tmp_path):
    root_dir = tmp_path / "nested" / "projects"
    store = ProjectStore(root_dir)

    store.save(_project())

    assert (root_dir / "proj_store_test.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_project_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.project_store'`.

- [ ] **Step 3: Implement `ProjectStore`**

Create `src/video_draft_pipeline/project_store.py`:

```python
from pathlib import Path

from .schema import Project


class ProjectStoreError(Exception):
    pass


class ProjectStore:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, project_id: str) -> Path:
        return self.root_dir / f"{project_id}.json"

    def save(self, project: Project) -> None:
        self._path_for(project.project_id).write_text(
            project.model_dump_json(indent=2), encoding="utf-8"
        )

    def load(self, project_id: str) -> Project:
        path = self._path_for(project_id)
        if not path.exists():
            raise ProjectStoreError(f"No stored project found for project_id={project_id!r}")
        try:
            return Project.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ProjectStoreError(
                f"Stored project file for project_id={project_id!r} is corrupt: {exc}"
            ) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_project_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/project_store.py tests/test_project_store.py
git commit -m "feat: add file-backed ProjectStore for persisting Project state"
```

---

### Task 3: Orchestrator — unresolved scenes no longer abort the run

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `ProjectStore` (Task 2), `Scene.needs_manual_fix` / `Project.running_cost_usd` (Task 1).
- Produces: `run_pipeline(..., project_store: ProjectStore | None = None)` (new optional param); `format_candidate_diagnostics(candidates: list[Candidate]) -> str` (renamed from the private `_format_candidate_diagnostics`, now a public module-level function — Task 5 and Task 6 import it); `_run_assembly(project: Project, assembly_output_path=None) -> None` (private helper, reused by Task 4's `resume_scene_with_image`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_orchestrator.py`, replace `test_run_pipeline_raises_when_review_always_fails` (the whole function) with:

```python
def test_run_pipeline_marks_all_scenes_needs_manual_fix_when_review_always_fails(monkeypatch):
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )

    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.ReviewAgent", FailingReviewAgent
    )

    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert len(project.scenes) == 4
    for scene in project.scenes:
        assert scene.needs_manual_fix is True
        assert scene.accepted_candidate_id is None
        assert scene.render is None
        assert scene.candidates[-1].consistency_review.issues == ["forced failure for test"]
```

Add a new test directly after it, reusing the module's existing `FakeStoryboardAgent`/`Storyboard` imports plus two new small fakes:

```python
class TwoSceneStoryboardAgent:
    def run(self, narrative, project_input):
        storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
        return [
            Scene(scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5, storyboard=storyboard),
            Scene(scene_id="scene_bad", beat_id="conflict", order=2, duration_sec=5, storyboard=storyboard),
        ]

    def estimate_cost(self):
        return 0.0


class SceneTaggingPromptAgent:
    def run(self, scene, feedback=None):
        return Prompts(image_prompt=f"prompt-for-{scene.scene_id}", video_motion_prompt="motion")

    def estimate_cost(self):
        return 0.0


class FailOnlyForBadScenePromptReviewAgent:
    def run(self, candidate, prior_candidates, prompts):
        if "scene_bad" in prompts.image_prompt:
            return ConsistencyReview(reviewed_by="fake", passed=False, issues=["forced failure for test"])
        return ConsistencyReview(reviewed_by="fake", passed=True, issues=[])

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_skips_assembly_when_any_scene_needs_manual_fix(monkeypatch):
    mock_assemble = MagicMock()
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        storyboard_agent=TwoSceneStoryboardAgent(),
        prompt_agent=SceneTaggingPromptAgent(),
        review_agent=FailOnlyForBadScenePromptReviewAgent(),
        assemble=True,
    )

    ok_scene = next(s for s in project.scenes if s.scene_id == "scene_ok")
    bad_scene = next(s for s in project.scenes if s.scene_id == "scene_bad")
    assert ok_scene.needs_manual_fix is False
    assert ok_scene.render is not None
    assert bad_scene.needs_manual_fix is True
    assert bad_scene.render is None
    assert project.output_video_url is None
    mock_assemble.assert_not_called()
```

Add one more test verifying `project.running_cost_usd` tracks the running cost and `format_candidate_diagnostics` is importable:

```python
def test_run_pipeline_persists_running_cost_on_project():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    expected_total = sum(scene.render.cost_usd for scene in project.scenes)
    assert project.running_cost_usd >= expected_total


def test_format_candidate_diagnostics_formats_attempt_lines():
    from video_draft_pipeline.orchestrator import format_candidate_diagnostics

    review = ConsistencyReview(reviewed_by="r", passed=False, issues=["issue-a"])
    decision = DirectorDecision(decision="regenerate", feedback="fix it", decided_by="d")
    candidate = Candidate(
        candidate_id="c1", image_url="u", generated_by="m",
        consistency_review=review, director_decision=decision,
    )

    text = format_candidate_diagnostics([candidate])

    assert "attempt 1" in text
    assert "issue-a" in text
    assert "regenerate" in text
```

Finally, add a test for the new `project_store` param:

```python
def test_run_pipeline_checkpoints_each_scene_to_project_store(tmp_path):
    from video_draft_pipeline.project_store import ProjectStore

    store = ProjectStore(tmp_path)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )

    project = run_pipeline(project_input, project_store=store)

    reloaded = store.load(project.project_id)
    assert len(reloaded.scenes) == 4
    assert reloaded.scenes[0].render is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -k "needs_manual_fix or skips_assembly or running_cost or format_candidate_diagnostics or checkpoints_each_scene" -v`
Expected: FAIL — the renamed test doesn't exist yet under the new name (or still asserts the old raising behavior), `format_candidate_diagnostics` isn't importable, and `project_store` isn't an accepted keyword argument.

- [ ] **Step 3: Rewrite the scene loop and assembly gating**

In `src/video_draft_pipeline/orchestrator.py`, change the import line at the top from:

```python
from .schema import BeatId, Candidate, Project, ProjectInput, Scene
```

to:

```python
from .schema import BeatId, Candidate, DirectorDecision, Project, ProjectInput, Scene
from .project_store import ProjectStore
```

Rename `_format_candidate_diagnostics` to `format_candidate_diagnostics` (drop the leading underscore — it's now reused by the CLI and A2A server in later tasks):

```python
def format_candidate_diagnostics(candidates: list[Candidate]) -> str:
    lines = []
    for i, c in enumerate(candidates, start=1):
        review = c.consistency_review
        decision = c.director_decision
        issues = ", ".join(review.issues) if review and review.issues else "none"
        review_passed = review.passed if review else None
        director_decision = decision.decision if decision else None
        feedback = decision.feedback if decision else None
        lines.append(
            f"  attempt {i}: review_passed={review_passed}, issues=[{issues}], "
            f"director={director_decision}, feedback={feedback!r}"
        )
    return "\n".join(lines)
```

Add a new private helper directly after `_charge`, factoring out the assembly logic that currently lives inline at the bottom of `run_pipeline`:

```python
def _run_assembly(project: Project, assembly_output_path: str | Path | None = None) -> None:
    output_path = str(assembly_output_path) if assembly_output_path else f"media/{project.project_id}.mp4"
    ordered_clip_paths = [
        scene.render.clip_url for scene in sorted(project.scenes, key=lambda s: s.order)
    ]
    try:
        project.output_video_url = assembly.assemble(ordered_clip_paths, output_path)
    except FileNotFoundError as exc:
        raise PipelineError(
            f"Video assembly failed: {exc}. Is ffmpeg installed and on PATH?"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(
            f"Video assembly failed: {exc}. If any scene's render backend is the stub "
            "StubRenderBackend, its stub:// clip URLs are not real files ffmpeg can read "
            "— inject a real render backend (e.g. VeoBackend, LTXBackend) to assemble "
            "real output."
        ) from exc
```

Add `project_store: ProjectStore | None = None` as the last parameter of `run_pipeline`'s signature (directly after `assembly_output_path: str | Path | None = None,`).

Replace the entire scene loop and assembly block (from `for scene in scenes:` through the end of the function) with:

```python
    for scene in scenes:
        running_cost = _charge(running_cost, prompt_agent.estimate_cost(), project_input.max_budget_usd)
        scene.prompts = prompt_agent.run(scene)

        max_attempts = scene.max_retries + 1
        for _ in range(max_attempts):
            candidate, running_cost = _generate_candidate(
                scene, prompt_agent, image_agent, image_edit_agent, running_cost, project_input.max_budget_usd
            )
            running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.consistency_review = review_agent.run(candidate, scene.candidates, scene.prompts)
            running_cost = _charge(running_cost, director_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
            scene.candidates.append(candidate)

            if candidate.director_decision.decision == "accept":
                scene.accepted_candidate_id = candidate.candidate_id
                break
            if candidate.director_decision.decision == "reject":
                break
            scene.retry_count += 1

        if scene.accepted_candidate_id is None:
            # Retries exhausted (or DirectorAgent never reached a terminal
            # accept/reject within max_attempts) without an accepted candidate.
            # This is no longer fatal to the whole run: keep the last
            # candidate's image, skip this scene's video render, and let the
            # rest of the project finish. A human can resume this scene later
            # via resume_scene_with_image with a replacement image.
            scene.needs_manual_fix = True
        else:
            try:
                render_result = render_agent.run(scene, running_cost, project_input.max_budget_usd)
            except BudgetExceededError as exc:
                raise PipelineError(str(exc)) from exc
            scene.render = render_result
            running_cost += render_result.cost_usd

        project.running_cost_usd = running_cost
        project.scenes.append(scene)
        if project_store is not None:
            project_store.save(project)

    if assemble and all(not scene.needs_manual_fix for scene in project.scenes):
        _run_assembly(project, assembly_output_path)
        if project_store is not None:
            project_store.save(project)

    return project
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS — every test in the file, including all pre-existing ones (none of the other existing tests hit the removed `for...else`/rejection-raise paths under conditions that still raise, since they're all budget-guard-driven or fully-passing scenarios).

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: scene review failure no longer aborts the whole pipeline run"
```

---

### Task 4: `resume_scene_with_image`

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py` (import additions only)

**Interfaces:**
- Consumes: `format_candidate_diagnostics`, `_run_assembly`, `ProjectStore` (all Task 3/2), `VideoRenderAgent.run(scene, current_cost_usd, max_budget_usd) -> RenderResult` (existing, `src/video_draft_pipeline/agents/video_render_agent.py`).
- Produces: `resume_scene_with_image(project: Project, scene_id: str, image_path: str, render_agent: VideoRenderAgent, project_store: ProjectStore | None = None) -> Project`. Tasks 5, 6, 7 all call this exact function.

- [ ] **Step 1: Write the failing tests**

In `tests/test_orchestrator.py`, add `Project` to the existing `from video_draft_pipeline.schema import (...)` import block (it currently imports `Beat, Candidate, ConsistencyReview, DirectorDecision, Narrative, ProjectInput, Prompts, RenderResult, Scene, Storyboard` — add `Project` alphabetically). Add these imports near the top of the file, alongside the existing `from video_draft_pipeline...` imports:

```python
from video_draft_pipeline.orchestrator import resume_scene_with_image
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent
from video_draft_pipeline.project_store import ProjectStore
```

Add at the end of `tests/test_orchestrator.py`:

```python
def _project_with_two_scenes(*, bad_needs_fix=True) -> Project:
    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event")
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    ok_scene = Scene(
        scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        accepted_candidate_id="cand_ok",
        candidates=[Candidate(candidate_id="cand_ok", image_url="stub://ok.png", generated_by="m")],
        render=RenderResult(backend="veo-3.1-fast", status="done", clip_url="stub://veo/cand_ok.mp4", cost_usd=0.5),
    )
    bad_scene = Scene(
        scene_id="scene_bad", beat_id="conflict", order=2, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=bad_needs_fix,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    project = Project(project_id="proj_resume_test", input=project_input, running_cost_usd=0.5)
    project.scenes = [ok_scene, bad_scene]
    return project


def test_resume_scene_with_image_resolves_target_scene_only(monkeypatch):
    # _project_with_two_scenes has exactly one needs_manual_fix scene, so
    # resuming it fully resolves the project and would trigger a real
    # assembly.assemble() (real ffmpeg subprocess) against fake stub://
    # clip URLs, which would fail — mock it out; this test isn't about
    # assembly.
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", MagicMock())
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    updated = resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent)

    bad_scene = next(s for s in updated.scenes if s.scene_id == "scene_bad")
    ok_scene = next(s for s in updated.scenes if s.scene_id == "scene_ok")
    assert bad_scene.needs_manual_fix is False
    assert bad_scene.render is not None
    assert bad_scene.render.status == "done"
    assert bad_scene.candidates[-1].image_url == "stub://fixed.png"
    assert bad_scene.candidates[-1].generated_by == "manual_upload"
    assert len(ok_scene.candidates) == 1


def test_resume_scene_with_image_triggers_assembly_when_last_unresolved_scene(monkeypatch):
    mock_assemble = MagicMock(return_value="media/proj_resume_test.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    updated = resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent)

    assert updated.output_video_url == "media/proj_resume_test.mp4"
    clip_paths_arg, output_path_arg = mock_assemble.call_args[0]
    assert output_path_arg == "media/proj_resume_test.mp4"
    assert clip_paths_arg == [updated.scenes[0].render.clip_url, updated.scenes[1].render.clip_url]


def test_resume_scene_with_image_raises_when_scene_not_found():
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(PipelineError):
        resume_scene_with_image(project, "scene_missing", "stub://fixed.png", render_agent)


def test_resume_scene_with_image_raises_when_scene_does_not_need_fix():
    project = _project_with_two_scenes(bad_needs_fix=False)
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(PipelineError):
        resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent)


def test_resume_scene_with_image_persists_via_project_store_when_given(tmp_path, monkeypatch):
    # Same reasoning as test_resume_scene_with_image_resolves_target_scene_only:
    # this fully resolves the project, so mock assembly to avoid a real
    # ffmpeg call against fake stub:// clip URLs.
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", MagicMock())
    project = _project_with_two_scenes()
    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))
    store = ProjectStore(tmp_path)

    resume_scene_with_image(project, "scene_bad", "stub://fixed.png", render_agent, project_store=store)

    reloaded = store.load(project.project_id)
    assert reloaded.scenes[1].needs_manual_fix is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -k resume_scene_with_image -v`
Expected: FAIL — `ImportError: cannot import name 'resume_scene_with_image'`.

- [ ] **Step 3: Implement `resume_scene_with_image`**

In `src/video_draft_pipeline/orchestrator.py`, add at the end of the file:

```python
def resume_scene_with_image(
    project: Project,
    scene_id: str,
    image_path: str,
    render_agent,
    project_store: ProjectStore | None = None,
) -> Project:
    scene = next((s for s in project.scenes if s.scene_id == scene_id), None)
    if scene is None:
        raise PipelineError(f"Scene {scene_id} not found on project {project.project_id}")
    if not scene.needs_manual_fix:
        raise PipelineError(f"Scene {scene_id} does not need a manual fix; nothing to resume")

    candidate = Candidate(
        candidate_id=f"cand_{uuid.uuid4().hex[:8]}",
        image_url=image_path,
        generated_by="manual_upload",
        director_decision=DirectorDecision(decision="accept", decided_by="human_manual_upload"),
    )
    scene.candidates.append(candidate)
    scene.accepted_candidate_id = candidate.candidate_id
    scene.needs_manual_fix = False

    try:
        render_result = render_agent.run(scene, project.running_cost_usd, project.input.max_budget_usd)
    except BudgetExceededError as exc:
        raise PipelineError(str(exc)) from exc
    scene.render = render_result
    project.running_cost_usd += render_result.cost_usd

    if all(not s.needs_manual_fix for s in project.scenes):
        _run_assembly(project)

    if project_store is not None:
        project_store.save(project)

    return project
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS — full file, including all Task 3 tests still passing.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add resume_scene_with_image for manual scene recovery"
```

---

### Task 5: CLI — `--project-store-dir` and the `resume` subcommand

**Files:**
- Modify: `src/video_draft_pipeline/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_pipeline(..., project_store=...)`, `resume_scene_with_image`, `format_candidate_diagnostics`, `PipelineError` (Tasks 3/4), `ProjectStore`/`ProjectStoreError` (Task 2), `VideoRenderAgent`, `StubRenderBackend`, `ModelConfig`.
- Produces: `parse_args`/`main` (existing, extended — unchanged call signature for existing callers), `parse_resume_args(argv) -> Namespace`, `resume_main(argv) -> int`, `cli_main(argv=None) -> int` (new top-level dispatcher; `if __name__ == "__main__"` now calls this).

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, update the existing `test_main_prints_valid_project_json` to isolate project-store writes to a temp dir:

```python
def test_main_prints_valid_project_json(capsys, tmp_path):
    exit_code = main(
        [
            "--preset", "이벤트", "--scene-type", "인게임", "--duration", "30", "--brief", "Halloween Event",
            "--project-store-dir", str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert "scenes" in payload
    assert len(payload["scenes"]) == 4
```

Update `test_main_returns_1_on_pipeline_error_without_traceback` the same way:

```python
def test_main_returns_1_on_pipeline_error_without_traceback(capsys, tmp_path):
    exit_code = main(
        [
            "--preset", "이벤트",
            "--scene-type", "인게임",
            "--duration", "30",
            "--brief", "Too expensive",
            "--max-budget", "0.01",
            "--project-store-dir", str(tmp_path),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert len(captured.err.strip().splitlines()) == 1
```

Add an assertion to `test_parse_args_reads_required_flags` (append to the existing function body, don't remove anything):

```python
    assert args.project_store_dir == "media/projects"
```

Add new tests at the end of the file:

```python
from video_draft_pipeline.cli import cli_main, parse_resume_args, resume_main
from video_draft_pipeline.project_store import ProjectStore
from video_draft_pipeline.schema import Candidate, Project, ProjectInput, Scene, Storyboard, Prompts


def test_parse_resume_args_reads_required_flags():
    args = parse_resume_args(
        [
            "--project-store-dir", "media/projects",
            "--project-id", "proj_1",
            "--scene-id", "scene_02",
            "--image", "fixed.png",
        ]
    )

    assert args.project_store_dir == "media/projects"
    assert args.project_id == "proj_1"
    assert args.scene_id == "scene_02"
    assert args.image_path == "fixed.png"


def _stored_project_needing_fix(tmp_path) -> str:
    # Two needs_manual_fix scenes, not one: resuming only "scene_bad" leaves
    # "scene_other" unresolved, so the project never reaches full resolution
    # and resume_scene_with_image never attempts a real assembly.assemble()
    # (real ffmpeg subprocess) against these tests' fake stub:// clip URLs.
    store = ProjectStore(tmp_path)
    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=5, brief="테스트")
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    other_scene = Scene(
        scene_id="scene_other", beat_id="conflict", order=2, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_other_1", image_url="stub://other.png", generated_by="m")],
    )
    project = Project(project_id="proj_cli_resume_test", input=project_input)
    project.scenes = [scene, other_scene]
    store.save(project)
    return project.project_id


def test_resume_main_prints_updated_project_json_on_success(capsys, tmp_path):
    project_id = _stored_project_needing_fix(tmp_path)

    exit_code = resume_main(
        [
            "--project-store-dir", str(tmp_path),
            "--project-id", project_id,
            "--scene-id", "scene_bad",
            "--image", "stub://fixed.png",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["scenes"][0]["needs_manual_fix"] is False


def test_resume_main_returns_1_when_project_not_found(capsys, tmp_path):
    exit_code = resume_main(
        [
            "--project-store-dir", str(tmp_path),
            "--project-id", "does-not-exist",
            "--scene-id", "scene_bad",
            "--image", "stub://fixed.png",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_cli_main_dispatches_resume_subcommand(capsys, tmp_path):
    project_id = _stored_project_needing_fix(tmp_path)

    exit_code = cli_main(
        [
            "resume",
            "--project-store-dir", str(tmp_path),
            "--project-id", project_id,
            "--scene-id", "scene_bad",
            "--image", "stub://fixed.png",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["scenes"][0]["needs_manual_fix"] is False


def test_cli_main_dispatches_bare_flags_to_run(capsys, tmp_path):
    exit_code = cli_main(
        [
            "--preset", "이벤트", "--scene-type", "인게임", "--duration", "10", "--brief", "Halloween Event",
            "--project-store-dir", str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert len(payload["scenes"]) == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError` for `cli_main`/`parse_resume_args`/`resume_main`, and `AttributeError`/`TypeError` for `--project-store-dir` not being a recognized flag on `main`'s existing tests.

- [ ] **Step 3: Implement**

Replace the full contents of `src/video_draft_pipeline/cli.py`:

```python
import argparse
import json
import sys

from pydantic import ValidationError

from .agents.video_render_agent import VideoRenderAgent
from .config import ModelConfig
from .orchestrator import PipelineError, format_candidate_diagnostics, resume_scene_with_image, run_pipeline
from .project_store import ProjectStore, ProjectStoreError
from .render_backends.stub_backend import StubRenderBackend
from .schema import ProjectInput


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the video draft pipeline end-to-end (stub agents)."
    )
    parser.add_argument("--preset", required=True, choices=["공개", "이벤트", "커뮤니티"])
    parser.add_argument(
        "--scene-type", required=True, choices=["인게임", "스튜디오"], dest="scene_type"
    )
    parser.add_argument("--duration", required=True, type=int, dest="duration_sec")
    parser.add_argument("--brief", required=True)
    parser.add_argument("--max-budget", type=float, default=5.00, dest="max_budget_usd")
    parser.add_argument("--project-store-dir", default="media/projects", dest="project_store_dir")
    args = parser.parse_args(argv)
    if args.max_budget_usd <= 0:
        parser.error(f"--max-budget must be greater than 0 (got {args.max_budget_usd})")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        project_input = ProjectInput(
            preset=args.preset,
            scene_type=args.scene_type,
            duration_sec=args.duration_sec,
            brief=args.brief,
            max_budget_usd=args.max_budget_usd,
        )
        project_store = ProjectStore(args.project_store_dir)
        project = run_pipeline(project_input, project_store=project_store)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        print(f"error: invalid input: {errors}", file=sys.stderr)
        return 1
    except PipelineError as exc:
        print(f"error: pipeline failed: {exc}", file=sys.stderr)
        return 1

    unresolved = [scene for scene in project.scenes if scene.needs_manual_fix]
    if unresolved:
        lines = [
            "warning: the following scenes need a manual fix — resume with "
            "`python -m video_draft_pipeline.cli resume --project-store-dir "
            f"{args.project_store_dir} --project-id {project.project_id} --scene-id <id> --image <path>`:"
        ]
        for scene in unresolved:
            lines.append(f"  {scene.scene_id}: {scene.candidates[-1].image_url}")
            lines.append(format_candidate_diagnostics(scene.candidates))
        print("\n".join(lines), file=sys.stderr)

    print(json.dumps(project.model_dump(), ensure_ascii=False, indent=2))
    return 0


def parse_resume_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video_draft_pipeline.cli resume",
        description="Resume a scene that needs a manual fix by submitting a replacement image.",
    )
    parser.add_argument("--project-store-dir", required=True, dest="project_store_dir")
    parser.add_argument("--project-id", required=True, dest="project_id")
    parser.add_argument("--scene-id", required=True, dest="scene_id")
    parser.add_argument("--image", required=True, dest="image_path")
    return parser.parse_args(argv)


def resume_main(argv: list[str] | None = None) -> int:
    args = parse_resume_args(argv)
    store = ProjectStore(args.project_store_dir)
    try:
        project = store.load(args.project_id)
    except ProjectStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier=ModelConfig().render_backend))
    try:
        project = resume_scene_with_image(
            project, args.scene_id, args.image_path, render_agent, project_store=store
        )
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(project.model_dump(), ensure_ascii=False, indent=2))
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["resume"]:
        return resume_main(argv[1:])
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli_main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS — full file.

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: PASS — every test in the repo (Tasks 1-5 combined).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/cli.py tests/test_cli.py
git commit -m "feat: add CLI resume subcommand and --project-store-dir"
```

---

### Task 6: A2A server — track `project_id`, report unresolved scenes

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/tasks.py`
- Modify: `src/video_draft_pipeline/a2a_server/render_runner.py`
- Modify: `tests/a2a_server/test_tasks.py`
- Modify: `tests/a2a_server/test_render_runner.py`

**Interfaces:**
- Consumes: `format_candidate_diagnostics`, `run_pipeline(..., project_store=...)` (Task 3), `ProjectStore` (Task 2).
- Produces: `TaskRecord.project_id: str | None`, `TaskStore.set_project_id(task_id, project_id) -> None`; `render_runner.PROJECT_STORE_DIR: str`, `render_runner.default_resume_render_agent() -> VideoRenderAgent` (Task 7 imports both of these).

- [ ] **Step 1: Write the failing tests**

In `tests/a2a_server/test_tasks.py`, add:

```python
def test_set_project_id_updates_record():
    store = TaskStore()
    record = store.create()

    store.set_project_id(record.task_id, "proj_abc123")

    assert store.get(record.task_id).project_id == "proj_abc123"


def test_create_returns_record_with_project_id_none():
    store = TaskStore()

    record = store.create()

    assert record.project_id is None
```

In `tests/a2a_server/test_render_runner.py`, add `Scene`, `Storyboard`, `Prompts`, `Candidate` to the `from video_draft_pipeline.schema import ...` import line, and add these tests at the end of the file:

```python
def test_run_render_task_sets_project_id_on_success():
    store = TaskStore()
    record = store.create()

    def fake_render(project_input: ProjectInput) -> Project:
        return Project(project_id="proj_abc123", input=project_input, output_video_url="media/proj_abc123.mp4")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    assert store.get(record.task_id).project_id == "proj_abc123"


def test_run_render_task_marks_completed_with_unresolved_scenes_message():
    store = TaskStore()
    record = store.create()
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")

    def fake_render(project_input: ProjectInput) -> Project:
        scene = Scene(
            scene_id="scene_04", beat_id="resolution", order=4, duration_sec=5,
            storyboard=storyboard, prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
            needs_manual_fix=True,
            candidates=[Candidate(candidate_id="cand_1", image_url="media/a2a_server/cand_1.png", generated_by="m")],
        )
        project = Project(project_id="proj_partial", input=project_input)
        project.scenes = [scene]
        return project

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_COMPLETED"
    assert updated.project_id == "proj_partial"
    assert "scene_04" in updated.answer
    assert "http://localhost:8002/media/a2a_server/cand_1.png" in updated.answer
    assert f"/tasks/{record.task_id}/scenes/" in updated.answer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/test_tasks.py tests/a2a_server/test_render_runner.py -v`
Expected: FAIL — `AttributeError: 'TaskStore' object has no attribute 'set_project_id'`, `TaskRecord(...) has no field project_id`, and the new render_runner tests fail because `project_id` stays `None` / the unresolved-scenes message doesn't exist yet.

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
```

In `src/video_draft_pipeline/a2a_server/render_runner.py`, replace the file contents:

```python
import logging
from typing import Callable

from ..agents.factory import build_real_agents
from ..agents.video_render_agent import VideoRenderAgent
from ..orchestrator import PipelineError, format_candidate_diagnostics, run_pipeline
from ..project_store import ProjectStore
from ..render_backends.veo_backend import VeoBackend
from ..schema import Project, ProjectInput

OUTPUT_DIR = "media/a2a_server"
PROJECT_STORE_DIR = f"{OUTPUT_DIR}/projects"

logger = logging.getLogger(__name__)


def default_render(project_input: ProjectInput) -> Project:
    agents = build_real_agents(output_dir=OUTPUT_DIR, log_path=f"{OUTPUT_DIR}/agent_log.jsonl")
    backend = VeoBackend(tier="veo-3.1-fast", output_dir=OUTPUT_DIR)
    project_store = ProjectStore(PROJECT_STORE_DIR)
    return run_pipeline(
        project_input, render_backend=backend, assemble=True, project_store=project_store, **agents
    )


def default_resume_render_agent() -> VideoRenderAgent:
    return VideoRenderAgent(backend=VeoBackend(tier="veo-3.1-fast", output_dir=OUTPUT_DIR))


def _unresolved_scenes_message(project: Project, media_public_base_url: str, task_id: str) -> str:
    lines = ["일부 장면에 수동 수정이 필요합니다:"]
    for scene in project.scenes:
        if not scene.needs_manual_fix:
            continue
        last_image_url = f"{media_public_base_url}/{scene.candidates[-1].image_url}"
        lines.append(f"- {scene.scene_id}: {last_image_url}")
        lines.append(format_candidate_diagnostics(scene.candidates))
    lines.append(
        f"수정한 이미지를 POST /tasks/{task_id}/scenes/{{scene_id}}/resume 로 업로드해 주세요."
    )
    return "\n".join(lines)


def run_render_task(
    task_store,
    task_id: str,
    project_input: ProjectInput,
    media_public_base_url: str,
    render_fn: Callable[[ProjectInput], Project] = default_render,
) -> None:
    try:
        project = render_fn(project_input)
    except PipelineError as exc:
        task_store.mark_failed(task_id, f"영상 생성에 실패했습니다: {exc}")
        return
    except Exception:
        logger.exception("render_runner: unexpected error during render")
        task_store.mark_failed(task_id, "영상 생성 중 알 수 없는 오류가 발생했습니다.")
        return

    task_store.set_project_id(task_id, project.project_id)

    if any(scene.needs_manual_fix for scene in project.scenes):
        task_store.mark_completed(task_id, _unresolved_scenes_message(project, media_public_base_url, task_id))
        return

    url = f"{media_public_base_url}/{project.output_video_url}"
    task_store.mark_completed(task_id, f"영상 초안이 완성되었습니다.\n{url}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server -v`
Expected: PASS — full `a2a_server` test suite, including the two pre-existing `test_render_runner.py` tests (success and `PipelineError`/unexpected-exception cases), which are unaffected since their fake `Project`s have empty `scenes` lists.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/tasks.py src/video_draft_pipeline/a2a_server/render_runner.py tests/a2a_server/test_tasks.py tests/a2a_server/test_render_runner.py
git commit -m "feat: track project_id on tasks, report unresolved scenes after a partial run"
```

---

### Task 7: A2A server — `POST /tasks/{task_id}/scenes/{scene_id}/resume`

**Files:**
- Modify: `src/video_draft_pipeline/a2a_server/app.py`
- Create: `tests/a2a_server/test_resume_endpoint.py`

**Interfaces:**
- Consumes: `resume_scene_with_image`, `PipelineError` (Task 4); `ProjectStore`, `ProjectStoreError` (Task 2); `TaskStore.set_project_id`, `TaskRecord.project_id` (Task 6); `render_runner.default_resume_render_agent` (Task 6) — note `app.py`'s own default `ProjectStore` path is built independently (`{media_dir}/a2a_server/projects`) rather than importing `render_runner.PROJECT_STORE_DIR`, since it must be parameterized by `create_app`'s own `media_dir` rather than render_runner's fixed one; the two happen to match under default settings.
- Produces: `create_app(..., project_store: ProjectStore | None = None, resume_render_agent_fn: Callable[[], VideoRenderAgent] = default_resume_render_agent)` — new optional params, existing callers unaffected since both have defaults.

- [ ] **Step 1: Write the failing tests**

Create `tests/a2a_server/test_resume_endpoint.py`:

```python
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.tasks import TaskStore
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent
from video_draft_pipeline.project_store import ProjectStore
from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
from video_draft_pipeline.schema import Candidate, Project, ProjectInput, Prompts, RenderResult, Scene, Storyboard


def _stub_render_agent_fn():
    return VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))


def _project_input() -> ProjectInput:
    return ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="테스트")


def _storyboard() -> Storyboard:
    return Storyboard(camera="c", subject="s", action="a", setting="set")


def _setup_app(tmp_path, scenes):
    media_dir = tmp_path / "media"
    project_store = ProjectStore(media_dir / "a2a_server" / "projects")
    project = Project(project_id="proj_resume_endpoint_test", input=_project_input())
    project.scenes = scenes
    project_store.save(project)

    store = TaskStore()
    record = store.create()
    store.set_project_id(record.task_id, project.project_id)
    store.mark_completed(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    app = create_app(
        task_store=store,
        media_dir=str(media_dir),
        project_store=project_store,
        resume_render_agent_fn=_stub_render_agent_fn,
    )
    return TestClient(app), record.task_id, project.project_id


def test_resume_endpoint_fully_resolves_and_assembles(tmp_path, monkeypatch):
    mock_assemble = MagicMock(return_value="media/proj_resume_endpoint_test.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    ok_scene = Scene(
        scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        accepted_candidate_id="cand_ok",
        candidates=[Candidate(candidate_id="cand_ok", image_url="stub://ok.png", generated_by="m")],
        render=RenderResult(backend="veo-3.1-fast", status="done", clip_url="stub://veo/cand_ok.mp4", cost_usd=0.5),
    )
    bad_scene = Scene(
        scene_id="scene_bad", beat_id="conflict", order=2, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, _ = _setup_app(tmp_path, [ok_scene, bad_scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_bad/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scene_id"] == "scene_bad"
    assert body["resolved"] is True
    assert body["remaining_unresolved"] == []
    assert body["output_video_url"] == "http://localhost:8002/media/proj_resume_endpoint_test.mp4"


def test_resume_endpoint_leaves_other_unresolved_scenes_pending(tmp_path):
    target_scene = Scene(
        scene_id="scene_target", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_1", image_url="stub://bad.png", generated_by="m")],
    )
    other_scene = Scene(
        scene_id="scene_other", beat_id="conflict", order=2, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p2", video_motion_prompt="m2"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_2", image_url="stub://bad2.png", generated_by="m")],
    )
    client, task_id, _ = _setup_app(tmp_path, [target_scene, other_scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_target/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["remaining_unresolved"] == ["scene_other"]
    assert body["output_video_url"] is None


def test_resume_endpoint_404_for_unknown_task(tmp_path):
    media_dir = tmp_path / "media"
    app = create_app(
        task_store=TaskStore(),
        media_dir=str(media_dir),
        project_store=ProjectStore(media_dir / "a2a_server" / "projects"),
        resume_render_agent_fn=_stub_render_agent_fn,
    )
    client = TestClient(app)

    response = client.post(
        "/tasks/does-not-exist/scenes/scene_x/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 404
    assert response.json()["error"]["status"] == "NOT_FOUND"


def test_resume_endpoint_404_for_unknown_scene(tmp_path):
    scene = Scene(
        scene_id="scene_real", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_1", image_url="stub://bad.png", generated_by="m")],
    )
    client, task_id, _ = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_missing/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 404
    assert response.json()["error"]["status"] == "NOT_FOUND"


def test_resume_endpoint_400_for_scene_not_needing_fix(tmp_path):
    scene = Scene(
        scene_id="scene_fine", beat_id="setup", order=1, duration_sec=5,
        storyboard=_storyboard(), prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        accepted_candidate_id="cand_1",
        candidates=[Candidate(candidate_id="cand_1", image_url="stub://ok.png", generated_by="m")],
        render=RenderResult(backend="veo-3.1-fast", status="done", clip_url="stub://veo/cand_1.mp4", cost_usd=0.5),
    )
    client, task_id, _ = _setup_app(tmp_path, [scene])

    response = client.post(
        f"/tasks/{task_id}/scenes/scene_fine/resume",
        files={"file": ("fixed.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/a2a_server/test_resume_endpoint.py -v`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'project_store'` (and, once that's fixed in isolation, `404 Not Found` from FastAPI for the route not existing).

- [ ] **Step 3: Implement the endpoint**

In `src/video_draft_pipeline/a2a_server/app.py`, update the imports at the top of the file:

```python
import os
import uuid
from pathlib import Path
from typing import Callable

from fastapi import BackgroundTasks, FastAPI, File, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .agent_card import build_agent_card
from .brief_intake import BriefIntakeAgent, BriefIntakeError, IntakeResult
from .errors import error_response
from .render_runner import default_render, default_resume_render_agent, run_render_task
from .tasks import TaskStore
from ..agents.errors import MissingAPIKeyError
from ..agents.video_render_agent import VideoRenderAgent
from ..orchestrator import PipelineError, resume_scene_with_image
from ..project_store import ProjectStore, ProjectStoreError
from ..schema import Project, ProjectInput
```

Update the `create_app` signature (add two new parameters directly after `render_fn`):

```python
def create_app(
    self_internal_url: str | None = None,
    media_public_base_url: str | None = None,
    media_dir: str = "media",
    task_store: TaskStore | None = None,
    intake_agent: BriefIntakeAgent | None = None,
    render_fn: Callable[[ProjectInput], Project] = default_render,
    project_store: ProjectStore | None = None,
    resume_render_agent_fn: Callable[[], VideoRenderAgent] = default_resume_render_agent,
) -> FastAPI:
    internal_url = self_internal_url or os.environ.get("SELF_INTERNAL_URL", "http://video-agent:8002")
    store = task_store or TaskStore()
    media_url = media_public_base_url or os.environ.get("MEDIA_PUBLIC_BASE_URL", "http://localhost:8002")
    store_for_projects = project_store or ProjectStore(str(Path(media_dir) / "a2a_server" / "projects"))

    app = FastAPI()
    app.state.media_public_base_url = media_url
    app.state.task_store = store

    Path(media_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")
```

(Leave the `agent_card`, `get_task`, and `message_send` routes exactly as they are.) Add the new route directly after `message_send`, before `return app`:

```python
    @app.post("/tasks/{task_id}/scenes/{scene_id}/resume")
    async def resume_scene(task_id: str, scene_id: str, file: UploadFile = File(...)):
        record = store.get(task_id)
        if record is None or record.project_id is None:
            return error_response("NOT_FOUND", f"Unknown task: {task_id}")

        try:
            project = store_for_projects.load(record.project_id)
        except ProjectStoreError as exc:
            return error_response("NOT_FOUND", str(exc))

        scene = next((s for s in project.scenes if s.scene_id == scene_id), None)
        if scene is None:
            return error_response("NOT_FOUND", f"Unknown scene: {scene_id}")
        if not scene.needs_manual_fix:
            return error_response("INVALID_ARGUMENT", f"Scene {scene_id} does not need a manual fix")

        upload_dir = Path(media_dir) / "manual_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "upload.png").suffix or ".png"
        image_path = upload_dir / f"{project.project_id}_{scene_id}_{uuid.uuid4().hex[:8]}{suffix}"
        contents = await file.read()
        image_path.write_bytes(contents)

        try:
            project = await run_in_threadpool(
                resume_scene_with_image,
                project,
                scene_id,
                str(image_path),
                resume_render_agent_fn(),
                store_for_projects,
            )
        except PipelineError as exc:
            return error_response("UNAVAILABLE", str(exc))

        remaining = [s.scene_id for s in project.scenes if s.needs_manual_fix]
        output_video_url = f"{media_url}/{project.output_video_url}" if project.output_video_url else None
        return {
            "scene_id": scene_id,
            "resolved": True,
            "remaining_unresolved": remaining,
            "output_video_url": output_video_url,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/a2a_server -v`
Expected: PASS — full `a2a_server` test suite, including all pre-existing tests (`test_message_send.py`, `test_get_task_route.py`, etc. — none touch the new parameters or route).

- [ ] **Step 5: Run the entire suite**

Run: `pytest -v`
Expected: PASS — every test in the repo, all 7 tasks combined.

- [ ] **Step 6: Update the README**

In `README.md`, find the line (around line 30): `**Not yet built:** partial-success/per-scene resumability (one scene failing kills the whole run), a review/regenerate loop on the rendered video clip itself (only the keyframe image is reviewed today), and auth on the A2A server.` Replace it with:

```markdown
**Not yet built:** a review/regenerate loop on the rendered video clip itself (only the keyframe image is reviewed today), and auth on the A2A server.
```

In the "Running the A2A server" section, add a new subsection documenting the resume flow (find where the existing endpoints — `/.well-known/agent-card.json`, `/message:send`, `/tasks/{task_id}` — are documented, and add directly after them):

```markdown
### Resuming a scene that needs a manual fix

If a scene exhausts its retries without passing review, the run doesn't abort — that scene is skipped (no video render, no assembly) and the rest of the project finishes normally. The task's `TASK_STATE_COMPLETED` message will list which scenes need a fix and a link to each one's last generated image.

To resume: fix the image externally (e.g. Photoshop) and `POST` it as multipart form data:

```bash
curl -X POST http://localhost:8002/tasks/<task_id>/scenes/<scene_id>/resume \
  -F "file=@fixed_scene.png"
```

The response includes `remaining_unresolved` (any other scenes still needing a fix) and `output_video_url` (set only once every scene is resolved and final assembly has run). This is a plain REST endpoint, not part of the A2A `message:send` text-chat contract — the teammate's `A2AClient` doesn't call it.

The same resume flow is available without the server, via the CLI: `python -m video_draft_pipeline.cli resume --project-store-dir <dir> --project-id <id> --scene-id <id> --image <path>`.
```

- [ ] **Step 7: Commit**

```bash
git add src/video_draft_pipeline/a2a_server/app.py tests/a2a_server/test_resume_endpoint.py README.md
git commit -m "feat: add A2A server endpoint to resume a scene with a manually fixed image"
```
