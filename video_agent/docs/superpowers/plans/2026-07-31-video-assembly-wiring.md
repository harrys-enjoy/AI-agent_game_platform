# Video Assembly Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing (but never-called) `assembly.assemble()` ffmpeg concatenation function into `run_pipeline`, so a project's rendered scene clips can optionally be combined into one final video, setting `Project.output_video_url` — opt-in only, so the pipeline's offline-by-default guarantee stays intact.

**Architecture:** `assembly.assemble()` gains one line (create its output directory if missing, matching the convention every other real-file-writing component already follows). `run_pipeline` gains two new params — `assemble: bool = False` and `assembly_output_path: str | Path | None = None` — and, only when `assemble=True`, calls `assembly.assemble()` after the scene loop with clips ordered by `scene.order`, wrapping any ffmpeg failure into the existing `PipelineError` convention.

**Tech Stack:** Python 3.11+, pytest, `unittest.mock.MagicMock`, `subprocess` (already a stdlib dependency of `assembly.py`).

## Global Constraints

- `assemble` defaults to `False` — opt-in only. A `run_pipeline()` call that doesn't pass it must never touch `ffmpeg` or the filesystem for assembly, preserving the "runs offline unless real agents are explicitly injected" guarantee.
- No changes to `build_ffmpeg_concat_command` or `write_concat_list` — only `assemble()` itself gains the directory-creation line.
- ffmpeg failures (`subprocess.CalledProcessError`, `FileNotFoundError`) must be wrapped into `PipelineError`, matching every other pipeline failure's convention — never let a raw `subprocess`/OS exception escape `run_pipeline`.
- No live-ffmpeg tests anywhere — `subprocess.run` is mocked in `assembly.py`'s own tests, and `assembly.assemble` itself is mocked in `orchestrator.py`'s tests.
- No changes to any other stage's agents, protocols, or the render-backend selection mechanism from the prior plan — this plan touches only `assembly.py` and `orchestrator.py`.
- All existing tests must keep passing (272 as of the last branch) — this plan is purely additive, nothing existing needs updating.

---

### Task 1: `assembly.assemble()` — create its output directory

**Files:**
- Modify: `src/video_draft_pipeline/assembly.py`
- Test: `tests/test_assembly.py`

**Interfaces:**
- Consumes: nothing new (stdlib `subprocess`, `pathlib.Path`, already imported).
- Produces: `assemble(clip_paths: list[str], output_path: str) -> str` now creates `Path(output_path).parent` if missing before writing anything. `build_ffmpeg_concat_command`/`write_concat_list` signatures unchanged. Task 2 consumes `assemble`'s exact signature and its exception behavior (`subprocess.CalledProcessError` on ffmpeg failure, via `check=True`, unchanged).

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_assembly.py` in full:

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.assembly import assemble, build_ffmpeg_concat_command, write_concat_list


def test_build_ffmpeg_concat_command_shape():
    command = build_ffmpeg_concat_command(["a.mp4", "b.mp4"], "out.mp4")

    assert command[0] == "ffmpeg"
    assert "-i" in command
    i_index = command.index("-i")
    assert command[i_index + 1] == "out.txt"
    assert command[-1] == "out.mp4"


def test_build_ffmpeg_concat_command_rejects_empty_clip_list():
    with pytest.raises(ValueError):
        build_ffmpeg_concat_command([], "out.mp4")


def test_write_concat_list_writes_expected_format(tmp_path):
    concat_list_path = tmp_path / "list.txt"

    write_concat_list(["a.mp4", "b.mp4"], str(concat_list_path))

    content = concat_list_path.read_text(encoding="utf-8")
    assert content == "file 'a.mp4'\nfile 'b.mp4'\n"


def test_assemble_creates_output_directory_if_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("video_draft_pipeline.assembly.subprocess.run", MagicMock())
    output_path = tmp_path / "nested" / "output.mp4"
    assert not output_path.parent.exists()

    assemble(["a.mp4", "b.mp4"], str(output_path))

    assert output_path.parent.is_dir()


def test_assemble_writes_concat_list(monkeypatch, tmp_path):
    monkeypatch.setattr("video_draft_pipeline.assembly.subprocess.run", MagicMock())
    output_path = tmp_path / "output.mp4"

    assemble(["a.mp4", "b.mp4"], str(output_path))

    concat_list_path = output_path.with_suffix(".txt")
    assert concat_list_path.read_text(encoding="utf-8") == "file 'a.mp4'\nfile 'b.mp4'\n"


def test_assemble_calls_subprocess_with_expected_command(monkeypatch, tmp_path):
    mock_run = MagicMock()
    monkeypatch.setattr("video_draft_pipeline.assembly.subprocess.run", mock_run)
    output_path = tmp_path / "output.mp4"

    assemble(["a.mp4", "b.mp4"], str(output_path))

    expected_command = build_ffmpeg_concat_command(["a.mp4", "b.mp4"], str(output_path))
    mock_run.assert_called_once_with(expected_command, check=True)


def test_assemble_returns_output_path(monkeypatch, tmp_path):
    monkeypatch.setattr("video_draft_pipeline.assembly.subprocess.run", MagicMock())
    output_path = tmp_path / "output.mp4"

    result = assemble(["a.mp4", "b.mp4"], str(output_path))

    assert result == str(output_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_assembly.py -v`
Expected: FAIL on the 4 new `test_assemble_*` tests — `output_path.parent` doesn't get created (or the tests fail for other reasons since `assemble()`'s directory-creation line doesn't exist yet, and without it a nested `tmp_path / "nested"` directory that doesn't exist would make `write_concat_list`'s `open(..., "w")` raise `FileNotFoundError`). The 3 pre-existing tests should already pass unchanged.

- [ ] **Step 3: Write the implementation**

Replace `src/video_draft_pipeline/assembly.py` in full:

```python
import subprocess
from pathlib import Path


def build_ffmpeg_concat_command(clip_paths: list[str], output_path: str) -> list[str]:
    if not clip_paths:
        raise ValueError("clip_paths must not be empty")
    concat_list_path = str(Path(output_path).with_suffix(".txt"))
    return [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        output_path,
    ]


def write_concat_list(clip_paths: list[str], concat_list_path: str) -> None:
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for path in clip_paths:
            f.write(f"file '{path}'\n")


def assemble(clip_paths: list[str], output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    concat_list_path = str(Path(output_path).with_suffix(".txt"))
    write_concat_list(clip_paths, concat_list_path)
    command = build_ffmpeg_concat_command(clip_paths, output_path)
    subprocess.run(command, check=True)
    return output_path
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/assembly.py tests/test_assembly.py
git commit -m "feat: create output directory in assembly.assemble(), add missing test coverage"
```

---

### Task 2: `run_pipeline` threading

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `assembly.assemble(clip_paths, output_path) -> str` (Task 1), `schema.Project.output_video_url` (already exists, unchanged).
- Produces: `run_pipeline(..., assemble: bool = False, assembly_output_path: str | Path | None = None) -> Project`. Nothing downstream in this plan consumes this further.

- [ ] **Step 1: Write the failing tests**

In `tests/test_orchestrator.py`, add one new import at the top of the file, alongside the existing imports:

```python
import subprocess
```

No other new imports are needed — the tests below monkeypatch `"video_draft_pipeline.orchestrator.assembly.assemble"` as a dotted string path, which `monkeypatch.setattr` resolves without requiring the `assembly` module to be imported into the test file itself.

Append at the end of the file:

```python
def test_run_pipeline_does_not_assemble_by_default(monkeypatch):
    mock_assemble = MagicMock()
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert project.output_video_url is None
    mock_assemble.assert_not_called()


def test_run_pipeline_assembles_when_requested(monkeypatch):
    mock_assemble = MagicMock(return_value="media/fake-output.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, assemble=True)

    assert project.output_video_url == "media/fake-output.mp4"
    clip_paths_arg, output_path_arg = mock_assemble.call_args[0]
    assert output_path_arg == f"media/{project.project_id}.mp4"
    assert clip_paths_arg == [scene.render.clip_url for scene in project.scenes]


def test_run_pipeline_assembles_to_explicit_output_path(monkeypatch):
    mock_assemble = MagicMock(return_value="custom/path.mp4")
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, assemble=True, assembly_output_path="custom/path.mp4")

    assert project.output_video_url == "custom/path.mp4"
    _, output_path_arg = mock_assemble.call_args[0]
    assert output_path_arg == "custom/path.mp4"


def test_run_pipeline_wraps_ffmpeg_called_process_error(monkeypatch):
    mock_assemble = MagicMock(side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]))
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    with pytest.raises(PipelineError):
        run_pipeline(project_input, assemble=True)


def test_run_pipeline_wraps_missing_ffmpeg_binary(monkeypatch):
    mock_assemble = MagicMock(side_effect=FileNotFoundError("ffmpeg not found"))
    monkeypatch.setattr("video_draft_pipeline.orchestrator.assembly.assemble", mock_assemble)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    with pytest.raises(PipelineError):
        run_pipeline(project_input, assemble=True)
```

(The `from video_draft_pipeline import assembly` import is unused directly in the test bodies above — all monkeypatching targets `"video_draft_pipeline.orchestrator.assembly.assemble"` as a string path, which doesn't require the name in scope. Add the import anyway for clarity/consistency with how the module is referenced; it does not cause a lint failure in this project, which has no linter configured.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL — `run_pipeline` doesn't accept `assemble`/`assembly_output_path` yet (`TypeError: unexpected keyword argument`), and `video_draft_pipeline.orchestrator` has no `assembly` attribute to monkeypatch yet.

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/orchestrator.py`, add two imports at the top:

```python
import subprocess
import uuid
from pathlib import Path

from . import assembly
from .schema import BeatId, Project, ProjectInput
```

(this replaces the existing `import uuid` and `from .schema import BeatId, Project, ProjectInput` lines — the rest of the import block below them is unchanged)

change the `run_pipeline` signature:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    render_backend_by_beat: dict[BeatId, RenderBackend] | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
    director_agent: DirectorAgentProtocol | None = None,
    assemble: bool = False,
    assembly_output_path: str | Path | None = None,
) -> Project:
```

and change the function's ending — replace:

```python
        project.scenes.append(scene)

    return project
```

with:

```python
        project.scenes.append(scene)

    if assemble:
        output_path = str(assembly_output_path) if assembly_output_path else f"media/{project.project_id}.mp4"
        ordered_clip_paths = [
            scene.render.clip_url for scene in sorted(project.scenes, key=lambda s: s.order)
        ]
        try:
            project.output_video_url = assembly.assemble(ordered_clip_paths, output_path)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise PipelineError(
                f"Video assembly failed: {exc}. Is ffmpeg installed and on PATH?"
            ) from exc

    return project
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire optional video assembly into run_pipeline"
```

---

## Self-Review Notes

- **Spec coverage:** `assembly.assemble()`'s directory-creation fix and its first-ever test coverage (Task 1), `run_pipeline`'s opt-in `assemble`/`assembly_output_path` params with `PipelineError`-wrapped ffmpeg failures (Task 2) — every section of the approved spec is covered. The spec's non-goals (no transition logic, no cross-clip audio treatment, no changes to `build_ffmpeg_concat_command`/`write_concat_list`) are honored: neither task touches those functions' bodies or adds any audio/transition logic.
- **Placeholder scan:** no "TBD"/"handle appropriately"/"similar to Task N" phrasing; every step shows complete code.
- **Type consistency:** `assemble()`'s signature (`clip_paths: list[str], output_path: str) -> str`) is unchanged between Task 1's definition and Task 2's call site. `run_pipeline`'s new `assemble: bool`/`assembly_output_path: str | Path | None` param names match exactly between the plan's signature block and its usage in the function body.
- **Offline-by-default, explicitly verified:** Task 2's `test_run_pipeline_does_not_assemble_by_default` proves `assembly.assemble` is never called and `output_video_url` stays `None` when `assemble` isn't passed — directly re-asserting the guarantee this plan was designed around from the start, the same discipline applied to `VeoBackend`/`StubRenderBackend` and the per-scene backend selection plan earlier this session.
