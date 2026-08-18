# Video Draft Pipeline Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold a Python monorepo skeleton for a multi-agent pipeline that turns a structured creative brief (preset + scene type + duration) into a rendered `.mp4` video draft, with every agent stubbed to deterministic fake-but-schema-correct output so the full pipeline can be run and tested end-to-end before any real model API is wired in.

**Architecture:** A single Pydantic `Project`/`Scene` schema is the shared contract threaded through eight pipeline stages (Planning → Storyboard → [duration guard] → per-scene loop of Prompt → Image → Review → Director → [budget guard] → Video Render → Assembly). Each stage is its own stub class/function with a real, testable, deterministic implementation — not a TODO — so the orchestrator wiring is provably correct before real LLM/image/video API calls are added in a later plan. The Video Render stage is built behind a `RenderBackend` protocol with two interchangeable implementations (`VeoBackend`, `SelfHostedBackend`) so swapping renderers later requires no changes elsewhere.

**Tech Stack:** Python 3.11+, Pydantic v2 for schema/validation, pytest for tests, stdlib `subprocess`/`argparse`/`uuid`. No web framework — this scaffold is backend/orchestrator + CLI only, per project decision (UI is out of scope for this repo).

**Solo project note:** This is being built by one person, not a divided team — earlier planning assumed a 5-person split (UI/orchestration/video-API/prompt/review) borrowed from generic advice about this problem domain; that does not apply here. File boundaries below are kept clean and single-responsibility for maintainability, not for parallel ownership. A future "router agent" that merges this project with unrelated sibling agent-projects (built by teammates on their own separate topics) has been raised as a long-term idea but is explicitly out of scope for this plan — no integration surface for it is being built now.

## Global Constraints

- Python >= 3.11 (uses modern `X | None` union syntax natively).
- `max_duration_sec` hard cap = 30 seconds; storyboard output must never exceed it (enforced by `duration_guard`, not just prompted).
- `max_budget_usd` default = $5.00; render spend is checked against it before every paid render call (enforced by `budget_guard`).
- Veo 3.1 per-second pricing (paid tier, 720p unless noted): Lite $0.05, Fast $0.10, Standard $0.40 — hardcoded in `render_backends/veo_backend.py` as the source of truth for cost math.
- No real API calls in this plan. Every agent is a deterministic stub returning schema-valid fake data. Real model integration is a separate, later plan.
- Package layout uses `src/` layout with package name `video_draft_pipeline`.
- Pydantic field naming: Python reserves `pass` as a keyword, so the schema field is `passed` (not `pass`) on `ConsistencyReview` — every task must use `passed` consistently.

---

## File Structure

```
video-draft-pipeline/
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/
│   └── video_draft_pipeline/
│       ├── __init__.py
│       ├── schema.py                    # Task 2
│       ├── guards.py                    # Task 3
│       ├── config.py                    # Task 4
│       ├── orchestrator.py              # Task 14
│       ├── cli.py                       # Task 15
│       ├── assembly.py                  # Task 13
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── planning_agent.py        # Task 5
│       │   ├── storyboard_agent.py      # Task 6
│       │   ├── prompt_agent.py          # Task 7
│       │   ├── image_agent.py           # Task 8
│       │   ├── review_agent.py          # Task 9
│       │   ├── director_agent.py        # Task 10
│       │   └── video_render_agent.py    # Task 12
│       └── render_backends/
│           ├── __init__.py
│           ├── base.py                  # Task 11
│           ├── veo_backend.py           # Task 11
│           └── selfhosted_backend.py    # Task 11
└── tests/
    ├── __init__.py
    ├── test_setup.py                    # Task 1
    ├── test_schema.py                   # Task 2
    ├── test_guards.py                   # Task 3
    ├── test_config.py                   # Task 4
    ├── test_assembly.py                 # Task 13
    ├── test_orchestrator.py             # Task 14
    ├── test_cli.py                      # Task 15
    ├── agents/
    │   ├── __init__.py
    │   ├── test_planning_agent.py       # Task 5
    │   ├── test_storyboard_agent.py     # Task 6
    │   ├── test_prompt_agent.py         # Task 7
    │   ├── test_image_agent.py          # Task 8
    │   ├── test_review_agent.py         # Task 9
    │   ├── test_director_agent.py       # Task 10
    │   └── test_video_render_agent.py   # Task 12
    └── render_backends/
        ├── __init__.py
        ├── test_veo_backend.py          # Task 11
        └── test_selfhosted_backend.py   # Task 11
```

---

### Task 1: Project scaffolding & tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/video_draft_pipeline/__init__.py`
- Create: `tests/__init__.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Produces: `video_draft_pipeline.__version__: str` — later tasks don't depend on this, it's purely a tooling smoke test.

- [ ] **Step 1: Write the failing test**

`tests/test_setup.py`:
```python
from video_draft_pipeline import __version__


def test_package_importable_with_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline'`

- [ ] **Step 3: Create pyproject.toml**

```toml
[project]
name = "video-draft-pipeline"
version = "0.1.0"
description = "Multi-agent video concept draft generator (발주용 영상 시안 자동 생성)"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 4: Create .gitignore**

```
__pycache__/
*.pyc
.venv/
.env
*.egg-info/
.pytest_cache/
```

- [ ] **Step 5: Create .env.example**

```
OPENAI_API_KEY=
GEMINI_API_KEY=
NEMOTRON_API_KEY=
```

- [ ] **Step 6: Create package init files**

`src/video_draft_pipeline/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

- [ ] **Step 7: Install the package and dev dependencies**

Run: `pip install -e ".[dev]"`

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_setup.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git init
git add pyproject.toml .gitignore .env.example src/video_draft_pipeline/__init__.py tests/__init__.py tests/test_setup.py
git commit -m "chore: project scaffolding and tooling"
```

---

### Task 2: Scene schema (Pydantic models)

**Files:**
- Create: `src/video_draft_pipeline/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing (this is the foundational data contract).
- Produces: `ProjectInput`, `Beat`, `Narrative`, `Storyboard`, `Prompts`, `ConsistencyReview`, `DirectorDecision`, `Candidate`, `RenderResult`, `Scene`, `Project` — every later task imports from here.

- [ ] **Step 1: Write the failing test**

`tests/test_schema.py`:
```python
import pytest
from pydantic import ValidationError

from video_draft_pipeline.schema import (
    ProjectInput,
    Beat,
    Narrative,
    Storyboard,
    Scene,
    Project,
)


def test_project_input_valid():
    pi = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=30,
        brief="Halloween Event",
    )
    assert pi.max_duration_sec == 30
    assert pi.max_budget_usd == 5.00


def test_project_input_rejects_duration_over_cap():
    with pytest.raises(ValidationError):
        ProjectInput(
            preset="이벤트",
            scene_type="인게임",
            duration_sec=999,
            brief="too long",
        )


def test_project_input_rejects_invalid_preset():
    with pytest.raises(ValidationError):
        ProjectInput(
            preset="not-a-real-preset",
            scene_type="인게임",
            duration_sec=30,
            brief="bad preset",
        )


def test_scene_requires_positive_duration():
    storyboard = Storyboard(camera="pan", subject="boss", action="appears", setting="castle")
    with pytest.raises(ValidationError):
        Scene(
            scene_id="scene_01",
            beat_id="climax",
            order=1,
            duration_sec=0,
            storyboard=storyboard,
        )


def test_project_assembles_full_tree():
    pi = ProjectInput(preset="공개", scene_type="스튜디오", duration_sec=30, brief="Reveal")
    narrative = Narrative(beats=[Beat(beat_id="setup", description="calm", tone="calm")])
    project = Project(project_id="proj_1", input=pi, narrative=narrative)
    assert project.scenes == []
    assert project.output_video_url is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.schema'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/schema.py`:
```python
from typing import Literal
from pydantic import BaseModel, Field

Preset = Literal["공개", "이벤트", "커뮤니티"]
SceneType = Literal["인게임", "스튜디오"]
BeatId = Literal["setup", "conflict", "climax", "resolution"]
RenderBackendName = Literal["veo-3.1-lite", "veo-3.1-fast", "veo-3.1-standard", "self-hosted"]
RenderStatus = Literal["pending", "rendering", "done", "failed"]
Decision = Literal["accept", "regenerate", "reject"]


class ProjectInput(BaseModel):
    preset: Preset
    scene_type: SceneType
    duration_sec: int = Field(gt=0, le=30)
    brief: str
    brand_requirements: list[str] = Field(default_factory=list)
    max_duration_sec: int = 30
    max_budget_usd: float = 5.00


class Beat(BaseModel):
    beat_id: BeatId
    description: str
    tone: str


class Narrative(BaseModel):
    beats: list[Beat]


class Storyboard(BaseModel):
    camera: str
    subject: str
    action: str
    setting: str
    required_elements: list[str] = Field(default_factory=list)


class Prompts(BaseModel):
    image_prompt: str
    video_motion_prompt: str


class ConsistencyReview(BaseModel):
    reviewed_by: str
    passed: bool
    issues: list[str] = Field(default_factory=list)


class DirectorDecision(BaseModel):
    decision: Decision
    feedback: str | None = None
    decided_by: str


class Candidate(BaseModel):
    candidate_id: str
    image_url: str
    generated_by: str
    consistency_review: ConsistencyReview | None = None
    director_decision: DirectorDecision | None = None


class RenderResult(BaseModel):
    backend: RenderBackendName
    status: RenderStatus
    clip_url: str | None = None
    cost_usd: float = 0.0


class Scene(BaseModel):
    scene_id: str
    beat_id: BeatId
    order: int
    duration_sec: float = Field(gt=0)
    storyboard: Storyboard
    prompts: Prompts | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    accepted_candidate_id: str | None = None
    render: RenderResult | None = None
    retry_count: int = 0
    max_retries: int = 3


class Project(BaseModel):
    project_id: str
    input: ProjectInput
    narrative: Narrative | None = None
    scenes: list[Scene] = Field(default_factory=list)
    output_video_url: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/schema.py tests/test_schema.py
git commit -m "feat: add project/scene pydantic schema"
```

---

### Task 3: Pipeline guards (duration + budget)

**Files:**
- Create: `src/video_draft_pipeline/guards.py`
- Test: `tests/test_guards.py`

**Interfaces:**
- Consumes: `Scene` from `schema.py`.
- Produces: `duration_guard(scenes: list[Scene], max_duration_sec: float) -> float`, `budget_guard(current_cost_usd: float, additional_cost_usd: float, max_budget_usd: float) -> float`, `DurationExceededError`, `BudgetExceededError` — used by `orchestrator.py` (Task 14) and `video_render_agent.py` (Task 12).

- [ ] **Step 1: Write the failing test**

`tests/test_guards.py`:
```python
import pytest

from video_draft_pipeline.schema import Scene, Storyboard
from video_draft_pipeline.guards import (
    duration_guard,
    budget_guard,
    DurationExceededError,
    BudgetExceededError,
)


def _scene(duration_sec: float) -> Scene:
    return Scene(
        scene_id="scene_01",
        beat_id="setup",
        order=1,
        duration_sec=duration_sec,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
    )


def test_duration_guard_passes_under_cap():
    scenes = [_scene(10), _scene(10), _scene(10)]
    assert duration_guard(scenes, max_duration_sec=30) == 30


def test_duration_guard_raises_over_cap():
    scenes = [_scene(20), _scene(20)]
    with pytest.raises(DurationExceededError):
        duration_guard(scenes, max_duration_sec=30)


def test_budget_guard_passes_under_cap():
    assert budget_guard(current_cost_usd=2.0, additional_cost_usd=1.0, max_budget_usd=5.0) == 3.0


def test_budget_guard_raises_over_cap():
    with pytest.raises(BudgetExceededError):
        budget_guard(current_cost_usd=4.5, additional_cost_usd=1.0, max_budget_usd=5.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_guards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.guards'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/guards.py`:
```python
from .schema import Scene


class DurationExceededError(Exception):
    pass


class BudgetExceededError(Exception):
    pass


def duration_guard(scenes: list[Scene], max_duration_sec: float) -> float:
    total = sum(scene.duration_sec for scene in scenes)
    if total > max_duration_sec:
        raise DurationExceededError(
            f"Total scene duration {total}s exceeds cap of {max_duration_sec}s"
        )
    return total


def budget_guard(current_cost_usd: float, additional_cost_usd: float, max_budget_usd: float) -> float:
    projected = current_cost_usd + additional_cost_usd
    if projected > max_budget_usd:
        raise BudgetExceededError(
            f"Projected cost ${projected:.2f} exceeds budget cap of ${max_budget_usd:.2f}"
        )
    return projected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_guards.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/guards.py tests/test_guards.py
git commit -m "feat: add duration and budget guards"
```

---

### Task 4: Config module (API keys & model selection)

**Files:**
- Create: `src/video_draft_pipeline/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: environment variables `OPENAI_API_KEY`, `GEMINI_API_KEY`, `NEMOTRON_API_KEY`.
- Produces: `ModelConfig` (dataclass with default model names per stage), `ApiKeys` (dataclass), `load_api_keys() -> ApiKeys` — not consumed by other tasks in this plan yet (real API wiring is a future plan), but defines the naming convention agents will use later.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import os

from video_draft_pipeline.config import ModelConfig, load_api_keys


def test_model_config_defaults():
    cfg = ModelConfig()
    assert cfg.planning_model == "gpt-5.4"
    assert cfg.storyboard_model == "gpt-5.4"
    assert cfg.prompt_model == "gpt-5-mini"
    assert cfg.image_model == "gpt-image-2"
    assert cfg.image_edit_model == "gemini-2.5-flash-image"
    assert cfg.review_model == "gemini-3-pro-image"
    assert cfg.director_model == "nemotron-3-ultra"
    assert cfg.render_backend == "veo-3.1-fast"


def test_load_api_keys_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("NEMOTRON_API_KEY", raising=False)

    keys = load_api_keys()

    assert keys.openai_api_key == "test-openai-key"
    assert keys.gemini_api_key == "test-gemini-key"
    assert keys.nemotron_api_key is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.config'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/config.py`:
```python
import os
from dataclasses import dataclass


@dataclass
class ModelConfig:
    planning_model: str = "gpt-5.4"
    storyboard_model: str = "gpt-5.4"
    prompt_model: str = "gpt-5-mini"
    image_model: str = "gpt-image-2"
    image_edit_model: str = "gemini-2.5-flash-image"
    review_model: str = "gemini-3-pro-image"
    director_model: str = "nemotron-3-ultra"
    render_backend: str = "veo-3.1-fast"


@dataclass
class ApiKeys:
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    nemotron_api_key: str | None = None


def load_api_keys() -> ApiKeys:
    return ApiKeys(
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        nemotron_api_key=os.environ.get("NEMOTRON_API_KEY"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/config.py tests/test_config.py
git commit -m "feat: add model config and api key loading"
```

---

### Task 5: Planning Agent stub

**Files:**
- Create: `src/video_draft_pipeline/agents/__init__.py`
- Create: `src/video_draft_pipeline/agents/planning_agent.py`
- Test: `tests/agents/__init__.py`
- Test: `tests/agents/test_planning_agent.py`

**Interfaces:**
- Consumes: `ProjectInput` from `schema.py`.
- Produces: `PlanningAgent.run(project_input: ProjectInput) -> Narrative` — consumed by `orchestrator.py` (Task 14).

- [ ] **Step 1: Write the failing test**

`tests/agents/__init__.py`: empty file.

`tests/agents/test_planning_agent.py`:
```python
from video_draft_pipeline.schema import ProjectInput
from video_draft_pipeline.agents.planning_agent import PlanningAgent


def test_planning_agent_returns_four_beats_in_order():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )
    narrative = PlanningAgent().run(project_input)

    assert [beat.beat_id for beat in narrative.beats] == [
        "setup",
        "conflict",
        "climax",
        "resolution",
    ]
    assert all("Halloween Event" in beat.description for beat in narrative.beats)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_planning_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/agents/__init__.py`: empty file.

`src/video_draft_pipeline/agents/planning_agent.py`:
```python
from ..schema import Narrative, Beat, ProjectInput

BEAT_TEMPLATE: dict[str, tuple[str, str]] = {
    "setup": ("평화로운 상황 전개", "calm"),
    "conflict": ("사건 발생, 긴장감 고조", "tense"),
    "climax": ("절정, 핵심 비주얼 등장", "epic"),
    "resolution": ("마무리 및 브랜드 노출", "hype"),
}


class PlanningAgent:
    def run(self, project_input: ProjectInput) -> Narrative:
        beats = [
            Beat(beat_id=beat_id, description=f"{project_input.brief}: {desc}", tone=tone)
            for beat_id, (desc, tone) in BEAT_TEMPLATE.items()
        ]
        return Narrative(beats=beats)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_planning_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/__init__.py src/video_draft_pipeline/agents/planning_agent.py tests/agents/__init__.py tests/agents/test_planning_agent.py
git commit -m "feat: add planning agent stub"
```

---

### Task 6: Storyboard Agent stub

**Files:**
- Create: `src/video_draft_pipeline/agents/storyboard_agent.py`
- Test: `tests/agents/test_storyboard_agent.py`

**Interfaces:**
- Consumes: `Narrative`, `ProjectInput` from `schema.py`.
- Produces: `StoryboardAgent.run(narrative: Narrative, project_input: ProjectInput) -> list[Scene]` — consumed by `orchestrator.py` (Task 14). Guarantees `sum(scene.duration_sec) == project_input.duration_sec` exactly.

- [ ] **Step 1: Write the failing test**

`tests/agents/test_storyboard_agent.py`:
```python
from video_draft_pipeline.schema import ProjectInput, Narrative, Beat
from video_draft_pipeline.agents.storyboard_agent import StoryboardAgent


def test_storyboard_agent_splits_duration_evenly_with_remainder_on_last_scene():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )

    scenes = StoryboardAgent().run(narrative, project_input)

    assert len(scenes) == 4
    assert sum(scene.duration_sec for scene in scenes) == 30
    assert [scene.order for scene in scenes] == [1, 2, 3, 4]
    assert [scene.beat_id for scene in scenes] == [
        "setup",
        "conflict",
        "climax",
        "resolution",
    ]


def test_storyboard_agent_puts_brand_requirements_on_resolution_scene():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=20,
        brief="Halloween Event",
        brand_requirements=["이벤트 로고 노출"],
    )
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )

    scenes = StoryboardAgent().run(narrative, project_input)

    assert scenes[0].storyboard.required_elements == []
    assert scenes[1].storyboard.required_elements == ["이벤트 로고 노출"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_storyboard_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.storyboard_agent'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/agents/storyboard_agent.py`:
```python
from ..schema import Narrative, ProjectInput, Scene, Storyboard


class StoryboardAgent:
    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]:
        beats = narrative.beats
        n = len(beats)
        base = project_input.duration_sec // n
        remainder = project_input.duration_sec - base * n

        scenes: list[Scene] = []
        for i, beat in enumerate(beats):
            duration = base + (remainder if i == n - 1 else 0)
            scenes.append(
                Scene(
                    scene_id=f"scene_{i + 1:02d}",
                    beat_id=beat.beat_id,
                    order=i + 1,
                    duration_sec=duration,
                    storyboard=Storyboard(
                        camera="슬로우 팬",
                        subject=project_input.brief,
                        action=beat.description,
                        setting=project_input.scene_type,
                        required_elements=(
                            list(project_input.brand_requirements)
                            if beat.beat_id == "resolution"
                            else []
                        ),
                    ),
                )
            )
        return scenes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_storyboard_agent.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/storyboard_agent.py tests/agents/test_storyboard_agent.py
git commit -m "feat: add storyboard agent stub"
```

---

### Task 7: Prompt Agent stub

**Files:**
- Create: `src/video_draft_pipeline/agents/prompt_agent.py`
- Test: `tests/agents/test_prompt_agent.py`

**Interfaces:**
- Consumes: `Scene` from `schema.py`.
- Produces: `PromptAgent.run(scene: Scene) -> Prompts` — consumed by `orchestrator.py` (Task 14).

- [ ] **Step 1: Write the failing test**

`tests/agents/test_prompt_agent.py`:
```python
from video_draft_pipeline.schema import Scene, Storyboard
from video_draft_pipeline.agents.prompt_agent import PromptAgent


def test_prompt_agent_builds_image_and_motion_prompts():
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(
            camera="슬로우 팬, 성벽 따라 이동",
            subject="호박 몬스터 무리",
            action="성벽을 타고 올라옴",
            setting="성 외곽, 야간",
        ),
    )

    prompts = PromptAgent().run(scene)

    assert "호박 몬스터 무리" in prompts.image_prompt
    assert "성벽을 타고 올라옴" in prompts.image_prompt
    assert "슬로우 팬, 성벽 따라 이동" in prompts.video_motion_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_prompt_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.prompt_agent'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/agents/prompt_agent.py`:
```python
from ..schema import Scene, Prompts


class PromptAgent:
    def run(self, scene: Scene) -> Prompts:
        sb = scene.storyboard
        image_prompt = f"{sb.setting}, {sb.subject}, {sb.action}, camera: {sb.camera}"
        video_motion_prompt = f"{sb.camera}, {sb.action}"
        return Prompts(image_prompt=image_prompt, video_motion_prompt=video_motion_prompt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_prompt_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/prompt_agent.py tests/agents/test_prompt_agent.py
git commit -m "feat: add prompt agent stub"
```

---

### Task 8: Image Agent stub

**Files:**
- Create: `src/video_draft_pipeline/agents/image_agent.py`
- Test: `tests/agents/test_image_agent.py`

**Interfaces:**
- Consumes: `Prompts` from `schema.py`.
- Produces: `ImageAgent(model_name: str = "gpt-image-2").run(prompts: Prompts) -> Candidate` — consumed by `orchestrator.py` (Task 14).

- [ ] **Step 1: Write the failing test**

`tests/agents/test_image_agent.py`:
```python
from video_draft_pipeline.schema import Prompts
from video_draft_pipeline.agents.image_agent import ImageAgent


def test_image_agent_returns_candidate_with_stub_url():
    prompts = Prompts(image_prompt="a castle at night", video_motion_prompt="pan left")

    candidate = ImageAgent(model_name="gpt-image-2").run(prompts)

    assert candidate.generated_by == "gpt-image-2"
    assert candidate.image_url.startswith("stub://gpt-image-2/")
    assert candidate.candidate_id


def test_image_agent_generates_unique_candidate_ids():
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")
    agent = ImageAgent()

    c1 = agent.run(prompts)
    c2 = agent.run(prompts)

    assert c1.candidate_id != c2.candidate_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_image_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.image_agent'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/agents/image_agent.py`:
```python
import uuid

from ..schema import Prompts, Candidate


class ImageAgent:
    def __init__(self, model_name: str = "gpt-image-2"):
        self.model_name = model_name

    def run(self, prompts: Prompts) -> Candidate:
        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        return Candidate(
            candidate_id=candidate_id,
            image_url=f"stub://{self.model_name}/{candidate_id}.png",
            generated_by=self.model_name,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_image_agent.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/image_agent.py tests/agents/test_image_agent.py
git commit -m "feat: add image agent stub"
```

---

### Task 9: Review Agent stub

**Files:**
- Create: `src/video_draft_pipeline/agents/review_agent.py`
- Test: `tests/agents/test_review_agent.py`

**Interfaces:**
- Consumes: `Candidate` from `schema.py`.
- Produces: `ReviewAgent(reviewer_name: str = "gemini-3-pro-image").run(candidate: Candidate, prior_candidates: list[Candidate]) -> ConsistencyReview` — consumed by `orchestrator.py` (Task 14).

- [ ] **Step 1: Write the failing test**

`tests/agents/test_review_agent.py`:
```python
from video_draft_pipeline.schema import Candidate
from video_draft_pipeline.agents.review_agent import ReviewAgent


def test_review_agent_stub_always_passes_with_no_issues():
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")

    review = ReviewAgent(reviewer_name="gemini-3-pro-image").run(candidate, prior_candidates=[])

    assert review.reviewed_by == "gemini-3-pro-image"
    assert review.passed is True
    assert review.issues == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_review_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.review_agent'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/agents/review_agent.py`:
```python
from ..schema import Candidate, ConsistencyReview


class ReviewAgent:
    def __init__(self, reviewer_name: str = "gemini-3-pro-image"):
        self.reviewer_name = reviewer_name

    def run(self, candidate: Candidate, prior_candidates: list[Candidate]) -> ConsistencyReview:
        return ConsistencyReview(reviewed_by=self.reviewer_name, passed=True, issues=[])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_review_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/review_agent.py tests/agents/test_review_agent.py
git commit -m "feat: add review agent stub"
```

---

### Task 10: Director Agent stub

**Files:**
- Create: `src/video_draft_pipeline/agents/director_agent.py`
- Test: `tests/agents/test_director_agent.py`

**Interfaces:**
- Consumes: `Scene`, `ConsistencyReview` from `schema.py`.
- Produces: `DirectorAgent(director_name: str = "nemotron-3-ultra").run(scene: Scene, review: ConsistencyReview) -> DirectorDecision` — consumed by `orchestrator.py` (Task 14). Decision is `"accept"` if `review.passed`, `"reject"` if failed and `scene.retry_count >= scene.max_retries`, else `"regenerate"`.

- [ ] **Step 1: Write the failing test**

`tests/agents/test_director_agent.py`:
```python
from video_draft_pipeline.schema import Scene, Storyboard, ConsistencyReview
from video_draft_pipeline.agents.director_agent import DirectorAgent


def _scene(retry_count: int = 0, max_retries: int = 3) -> Scene:
    return Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        retry_count=retry_count,
        max_retries=max_retries,
    )


def test_director_accepts_when_review_passed():
    review = ConsistencyReview(reviewed_by="gemini-3-pro-image", passed=True, issues=[])

    decision = DirectorAgent().run(_scene(), review)

    assert decision.decision == "accept"
    assert decision.decided_by == "nemotron-3-ultra"


def test_director_regenerates_when_review_failed_and_retries_remain():
    review = ConsistencyReview(
        reviewed_by="gemini-3-pro-image", passed=False, issues=["색감 불일치"]
    )

    decision = DirectorAgent().run(_scene(retry_count=1, max_retries=3), review)

    assert decision.decision == "regenerate"
    assert "색감 불일치" in decision.feedback


def test_director_rejects_when_retries_exhausted():
    review = ConsistencyReview(
        reviewed_by="gemini-3-pro-image", passed=False, issues=["색감 불일치"]
    )

    decision = DirectorAgent().run(_scene(retry_count=3, max_retries=3), review)

    assert decision.decision == "reject"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_director_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.director_agent'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/agents/director_agent.py`:
```python
from ..schema import Scene, ConsistencyReview, DirectorDecision


class DirectorAgent:
    def __init__(self, director_name: str = "nemotron-3-ultra"):
        self.director_name = director_name

    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision:
        if review.passed:
            return DirectorDecision(decision="accept", decided_by=self.director_name)

        if scene.retry_count >= scene.max_retries:
            return DirectorDecision(
                decision="reject",
                feedback="Max retries exhausted without a passing review.",
                decided_by=self.director_name,
            )

        return DirectorDecision(
            decision="regenerate",
            feedback="; ".join(review.issues) or "Consistency review failed.",
            decided_by=self.director_name,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_director_agent.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/director_agent.py tests/agents/test_director_agent.py
git commit -m "feat: add director agent stub"
```

---

### Task 11: Render backends (Veo + self-hosted stub)

**Files:**
- Create: `src/video_draft_pipeline/render_backends/__init__.py`
- Create: `src/video_draft_pipeline/render_backends/base.py`
- Create: `src/video_draft_pipeline/render_backends/veo_backend.py`
- Create: `src/video_draft_pipeline/render_backends/selfhosted_backend.py`
- Test: `tests/render_backends/__init__.py`
- Test: `tests/render_backends/test_veo_backend.py`
- Test: `tests/render_backends/test_selfhosted_backend.py`

**Interfaces:**
- Consumes: `Candidate`, `RenderResult` from `schema.py`.
- Produces: `RenderBackend` protocol (`name: str`, `render(candidate, motion_prompt, duration_sec) -> RenderResult`), `VeoBackend(tier: str = "veo-3.1-fast")`, `PRICE_PER_SEC_USD: dict[str, float]`, `SelfHostedBackend(endpoint_url: str)` — consumed by `video_render_agent.py` (Task 12) and `orchestrator.py` (Task 14).

- [ ] **Step 1: Write the failing tests**

`tests/render_backends/__init__.py`: empty file.

`tests/render_backends/test_veo_backend.py`:
```python
import pytest

from video_draft_pipeline.schema import Candidate
from video_draft_pipeline.render_backends.veo_backend import VeoBackend


def _candidate() -> Candidate:
    return Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")


def test_veo_backend_fast_tier_cost_math():
    backend = VeoBackend(tier="veo-3.1-fast")

    result = backend.render(_candidate(), motion_prompt="pan left", duration_sec=6.0)

    assert result.backend == "veo-3.1-fast"
    assert result.status == "done"
    assert result.cost_usd == 0.60
    assert result.clip_url.startswith("stub://veo/")


def test_veo_backend_lite_tier_cost_math():
    backend = VeoBackend(tier="veo-3.1-lite")

    result = backend.render(_candidate(), motion_prompt="pan left", duration_sec=6.0)

    assert result.cost_usd == 0.30


def test_veo_backend_rejects_unknown_tier():
    with pytest.raises(ValueError):
        VeoBackend(tier="veo-9000")
```

`tests/render_backends/test_selfhosted_backend.py`:
```python
from video_draft_pipeline.schema import Candidate
from video_draft_pipeline.render_backends.selfhosted_backend import SelfHostedBackend


def test_selfhosted_backend_is_free_and_returns_clip():
    backend = SelfHostedBackend(endpoint_url="https://example-tunnel.ngrok.app")
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")

    result = backend.render(candidate, motion_prompt="pan left", duration_sec=6.0)

    assert result.backend == "self-hosted"
    assert result.status == "done"
    assert result.cost_usd == 0.0
    assert result.clip_url.startswith("stub://self-hosted/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/render_backends/ -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.render_backends'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/render_backends/__init__.py`: empty file.

`src/video_draft_pipeline/render_backends/base.py`:
```python
from typing import Protocol

from ..schema import Candidate, RenderResult


class RenderBackend(Protocol):
    name: str

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        ...
```

`src/video_draft_pipeline/render_backends/veo_backend.py`:
```python
from ..schema import Candidate, RenderResult

PRICE_PER_SEC_USD: dict[str, float] = {
    "veo-3.1-lite": 0.05,
    "veo-3.1-fast": 0.10,
    "veo-3.1-standard": 0.40,
}


class VeoBackend:
    def __init__(self, tier: str = "veo-3.1-fast"):
        if tier not in PRICE_PER_SEC_USD:
            raise ValueError(f"Unknown Veo tier: {tier}")
        self.tier = tier
        self.name = tier

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        cost = round(PRICE_PER_SEC_USD[self.tier] * duration_sec, 2)
        return RenderResult(
            backend=self.tier,
            status="done",
            clip_url=f"stub://veo/{candidate.candidate_id}.mp4",
            cost_usd=cost,
        )
```

`src/video_draft_pipeline/render_backends/selfhosted_backend.py`:
```python
from ..schema import Candidate, RenderResult


class SelfHostedBackend:
    name = "self-hosted"

    def __init__(self, endpoint_url: str):
        self.endpoint_url = endpoint_url

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        return RenderResult(
            backend="self-hosted",
            status="done",
            clip_url=f"stub://self-hosted/{candidate.candidate_id}.mp4",
            cost_usd=0.0,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/render_backends/ -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/render_backends/ tests/render_backends/
git commit -m "feat: add swappable render backends (veo, self-hosted stub)"
```

---

### Task 12: Video Render Agent (budget-guarded wrapper)

**Files:**
- Create: `src/video_draft_pipeline/agents/video_render_agent.py`
- Test: `tests/agents/test_video_render_agent.py`

**Interfaces:**
- Consumes: `Scene` from `schema.py`; `budget_guard`, `BudgetExceededError` from `guards.py`; `RenderBackend`, `PRICE_PER_SEC_USD` from `render_backends`.
- Produces: `VideoRenderAgent(backend: RenderBackend).run(scene: Scene, current_cost_usd: float, max_budget_usd: float) -> RenderResult` — consumed by `orchestrator.py` (Task 14). Raises `BudgetExceededError` before calling the backend if projected cost would exceed the cap. Raises `ValueError` if the scene has no accepted candidate.

- [ ] **Step 1: Write the failing test**

`tests/agents/test_video_render_agent.py`:
```python
import pytest

from video_draft_pipeline.schema import Scene, Storyboard, Candidate
from video_draft_pipeline.guards import BudgetExceededError
from video_draft_pipeline.render_backends.veo_backend import VeoBackend
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent


def _scene_with_accepted_candidate(duration_sec: float = 6.0) -> Scene:
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=duration_sec,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        candidates=[candidate],
        accepted_candidate_id="c1",
    )
    scene.prompts = None
    return scene


def test_video_render_agent_renders_under_budget():
    agent = VideoRenderAgent(backend=VeoBackend(tier="veo-3.1-fast"))

    result = agent.run(_scene_with_accepted_candidate(6.0), current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.status == "done"
    assert result.cost_usd == 0.60


def test_video_render_agent_raises_when_over_budget():
    agent = VideoRenderAgent(backend=VeoBackend(tier="veo-3.1-fast"))

    with pytest.raises(BudgetExceededError):
        agent.run(_scene_with_accepted_candidate(6.0), current_cost_usd=4.5, max_budget_usd=5.0)


def test_video_render_agent_raises_without_accepted_candidate():
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6.0,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
    )
    agent = VideoRenderAgent(backend=VeoBackend(tier="veo-3.1-fast"))

    with pytest.raises(ValueError):
        agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_video_render_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.video_render_agent'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/agents/video_render_agent.py`:
```python
from ..schema import Scene, RenderResult, Candidate
from ..guards import budget_guard
from ..render_backends.base import RenderBackend
from ..render_backends.veo_backend import PRICE_PER_SEC_USD


class VideoRenderAgent:
    def __init__(self, backend: RenderBackend):
        self.backend = backend

    def run(self, scene: Scene, current_cost_usd: float, max_budget_usd: float) -> RenderResult:
        estimated_cost = self._estimate_cost(scene)
        budget_guard(current_cost_usd, estimated_cost, max_budget_usd)

        candidate = self._accepted_candidate(scene)
        motion_prompt = scene.prompts.video_motion_prompt if scene.prompts else ""
        return self.backend.render(
            candidate=candidate,
            motion_prompt=motion_prompt,
            duration_sec=scene.duration_sec,
        )

    def _estimate_cost(self, scene: Scene) -> float:
        price = PRICE_PER_SEC_USD.get(self.backend.name, 0.0)
        return round(price * scene.duration_sec, 2)

    def _accepted_candidate(self, scene: Scene) -> Candidate:
        if scene.accepted_candidate_id is None:
            raise ValueError(f"Scene {scene.scene_id} has no accepted candidate")
        for candidate in scene.candidates:
            if candidate.candidate_id == scene.accepted_candidate_id:
                return candidate
        raise ValueError(
            f"Accepted candidate {scene.accepted_candidate_id} not found on scene {scene.scene_id}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_video_render_agent.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/video_render_agent.py tests/agents/test_video_render_agent.py
git commit -m "feat: add budget-guarded video render agent"
```

---

### Task 13: Final assembly (ffmpeg command builder)

**Files:**
- Create: `src/video_draft_pipeline/assembly.py`
- Test: `tests/test_assembly.py`

**Interfaces:**
- Consumes: `list[str]` of clip file paths.
- Produces: `build_ffmpeg_concat_command(clip_paths: list[str], output_path: str) -> list[str]`, `write_concat_list(clip_paths: list[str], concat_list_path: str) -> None`, `assemble(clip_paths: list[str], output_path: str) -> str` — consumed by a future orchestrator extension (not wired into `run_pipeline` in this plan; see Global Constraints — orchestrator produces per-scene render results, and calling real `ffmpeg` end-to-end is deferred since it requires actual media files, out of scope for stub-only scaffolding).

- [ ] **Step 1: Write the failing test**

`tests/test_assembly.py`:
```python
import pytest

from video_draft_pipeline.assembly import build_ffmpeg_concat_command, write_concat_list


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_assembly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.assembly'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/assembly.py`:
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
    concat_list_path = str(Path(output_path).with_suffix(".txt"))
    write_concat_list(clip_paths, concat_list_path)
    command = build_ffmpeg_concat_command(clip_paths, output_path)
    subprocess.run(command, check=True)
    return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_assembly.py -v`
Expected: PASS (3 tests)

Note: `assemble()` itself (the real `subprocess.run` call against actual ffmpeg and real clip files) is intentionally not covered by an automated test here — that requires ffmpeg installed and real media fixtures, which is integration-level testing out of scope for this stub-only scaffold. `build_ffmpeg_concat_command` and `write_concat_list` are the pure, fully-tested pieces; `assemble()` will get integration coverage once Task 14's future real-render follow-up plan produces actual clip files.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/assembly.py tests/test_assembly.py
git commit -m "feat: add ffmpeg concat assembly step"
```

---

### Task 14: Orchestrator (wires everything end-to-end)

**Files:**
- Create: `src/video_draft_pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: every agent class from Tasks 5-10 and 12, `duration_guard`/`DurationExceededError` from `guards.py`, `VeoBackend` from `render_backends`.
- Produces: `run_pipeline(project_input: ProjectInput, render_backend: RenderBackend | None = None) -> Project`, `PipelineError` — consumed by `cli.py` (Task 15).

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrator.py`:
```python
import pytest

from video_draft_pipeline.schema import ProjectInput
from video_draft_pipeline.orchestrator import run_pipeline, PipelineError


def test_run_pipeline_produces_fully_rendered_project():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert project.narrative is not None
    assert len(project.narrative.beats) == 4
    assert len(project.scenes) == 4
    assert sum(scene.duration_sec for scene in project.scenes) == 30

    for scene in project.scenes:
        assert scene.accepted_candidate_id is not None
        assert scene.render is not None
        assert scene.render.status == "done"

    total_cost = sum(scene.render.cost_usd for scene in project.scenes)
    assert total_cost <= project_input.max_budget_usd


def test_run_pipeline_raises_when_duration_exceeds_cap():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=30,
        brief="Halloween Event",
        max_duration_sec=10,
    )

    with pytest.raises(PipelineError):
        run_pipeline(project_input)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.orchestrator'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/orchestrator.py`:
```python
import uuid

from .schema import Project, ProjectInput
from .guards import duration_guard, DurationExceededError, BudgetExceededError
from .agents.planning_agent import PlanningAgent
from .agents.storyboard_agent import StoryboardAgent
from .agents.prompt_agent import PromptAgent
from .agents.image_agent import ImageAgent
from .agents.review_agent import ReviewAgent
from .agents.director_agent import DirectorAgent
from .agents.video_render_agent import VideoRenderAgent
from .render_backends.base import RenderBackend
from .render_backends.veo_backend import VeoBackend


class PipelineError(Exception):
    pass


def run_pipeline(project_input: ProjectInput, render_backend: RenderBackend | None = None) -> Project:
    project = Project(project_id=f"proj_{uuid.uuid4().hex[:8]}", input=project_input)

    planning_agent = PlanningAgent()
    storyboard_agent = StoryboardAgent()
    prompt_agent = PromptAgent()
    image_agent = ImageAgent()
    review_agent = ReviewAgent()
    director_agent = DirectorAgent()
    backend = render_backend or VeoBackend(tier="veo-3.1-fast")
    render_agent = VideoRenderAgent(backend=backend)

    narrative = planning_agent.run(project_input)
    project.narrative = narrative

    scenes = storyboard_agent.run(narrative, project_input)

    try:
        duration_guard(scenes, project_input.max_duration_sec)
    except DurationExceededError as exc:
        raise PipelineError(str(exc)) from exc

    running_cost = 0.0
    for scene in scenes:
        scene.prompts = prompt_agent.run(scene)

        while True:
            candidate = image_agent.run(scene.prompts)
            candidate.consistency_review = review_agent.run(candidate, scene.candidates)
            candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
            scene.candidates.append(candidate)

            if candidate.director_decision.decision == "accept":
                scene.accepted_candidate_id = candidate.candidate_id
                break
            if candidate.director_decision.decision == "reject":
                break
            scene.retry_count += 1

        if scene.accepted_candidate_id is not None:
            try:
                render_result = render_agent.run(scene, running_cost, project_input.max_budget_usd)
            except BudgetExceededError as exc:
                raise PipelineError(str(exc)) from exc
            scene.render = render_result
            running_cost += render_result.cost_usd

        project.scenes.append(scene)

    return project
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add orchestrator wiring full pipeline end-to-end"
```

---

### Task 15: CLI test harness

**Files:**
- Create: `src/video_draft_pipeline/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_pipeline` from `orchestrator.py`, `ProjectInput` from `schema.py`.
- Produces: `parse_args(argv: list[str] | None) -> argparse.Namespace`, `main(argv: list[str] | None) -> int` — this is the top-level entrypoint a developer runs manually; nothing in the plan consumes it further.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import json

from video_draft_pipeline.cli import parse_args, main


def test_parse_args_reads_required_flags():
    args = parse_args(
        ["--preset", "이벤트", "--scene-type", "인게임", "--duration", "30", "--brief", "Halloween Event"]
    )

    assert args.preset == "이벤트"
    assert args.scene_type == "인게임"
    assert args.duration_sec == 30
    assert args.brief == "Halloween Event"
    assert args.max_budget_usd == 5.00


def test_main_prints_valid_project_json(capsys):
    exit_code = main(
        ["--preset", "이벤트", "--scene-type", "인게임", "--duration", "30", "--brief", "Halloween Event"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert "scenes" in payload
    assert len(payload["scenes"]) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.cli'`

- [ ] **Step 3: Write the implementation**

`src/video_draft_pipeline/cli.py`:
```python
import argparse
import json
import sys

from .schema import ProjectInput
from .orchestrator import run_pipeline


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_input = ProjectInput(
        preset=args.preset,
        scene_type=args.scene_type,
        duration_sec=args.duration_sec,
        brief=args.brief,
        max_budget_usd=args.max_budget_usd,
    )
    project = run_pipeline(project_input)
    print(json.dumps(project.model_dump(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full test suite to confirm nothing regressed**

Run: `pytest -v`
Expected: PASS (all tests across all 15 tasks)

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/cli.py tests/test_cli.py
git commit -m "feat: add CLI test harness for end-to-end pipeline run"
```
