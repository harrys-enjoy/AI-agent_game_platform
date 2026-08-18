# Director-Feedback Retry-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `DirectorDecision.feedback` into real regenerate behavior: the first retry edits the rejected image via Gemini 2.5 Flash Image using the director's feedback; further retries fall back to a feedback-revised full regeneration.

**Architecture:** A new `ImageEditAgentProtocol` (stub `ImageEditAgent` + real `GeminiImageEditAgent`) slots into `run_pipeline` alongside the existing agent protocols. `PromptAgentProtocol.run` gains an optional `feedback` param. The orchestrator's per-attempt candidate generation is extracted into a `_generate_candidate` helper that branches on `scene.retry_count`: attempt 1 = fresh generate, attempt 2 = edit, attempt 3+ = feedback-revised regenerate-from-scratch.

**Tech Stack:** Python, pydantic, pytest, `unittest.mock.MagicMock`, OpenAI SDK (existing), Google `genai` SDK (existing).

## Global Constraints

- Work lands directly on `master` — no feature branches, no worktrees (this project's established convention).
- TDD throughout: write the failing test, confirm it fails, implement, confirm it passes, commit.
- Stub agents must never require a real API key or make network calls — this pipeline's offline-by-default invariant.
- Follow existing code conventions exactly: stub agent defaults use bare model names (e.g. `"gemini-2.5-flash-image"`, not `"google/gemini-2.5-flash-image"`), matching `ImageAgent`/`DirectorAgent`/`ReviewAgent`'s existing stub style.
- `Candidate`/`Prompts`/`Scene` schema types are not modified by this plan — only protocols, agents, and the orchestrator.

---

### Task 1: `ImageEditAgentProtocol` + stub `ImageEditAgent`

**Files:**
- Modify: `src/video_draft_pipeline/agents/protocols.py`
- Create: `src/video_draft_pipeline/agents/image_edit_agent.py`
- Create: `tests/agents/test_image_edit_agent.py`
- Modify: `tests/agents/test_protocols.py`

**Interfaces:**
- Produces: `ImageEditAgentProtocol.run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate`, `.estimate_cost() -> float`. Stub class `ImageEditAgent(model_name: str = "gemini-2.5-flash-image")` implementing it.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_image_edit_agent.py`:

```python
from video_draft_pipeline.schema import Candidate, Prompts
from video_draft_pipeline.agents.image_edit_agent import ImageEditAgent


def _prior_candidate() -> Candidate:
    return Candidate(
        candidate_id="cand_prior", image_url="stub://gpt-image-2/cand_prior.png", generated_by="gpt-image-2"
    )


def test_image_edit_agent_returns_candidate_with_stub_url():
    prompts = Prompts(image_prompt="a castle at night", video_motion_prompt="pan left")

    candidate = ImageEditAgent(model_name="gemini-2.5-flash-image").run(
        _prior_candidate(), prompts, feedback="fix the lighting"
    )

    assert candidate.generated_by == "gemini-2.5-flash-image"
    assert candidate.image_url.startswith("stub://gemini-2.5-flash-image/")
    assert candidate.candidate_id


def test_image_edit_agent_generates_unique_candidate_ids():
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")
    agent = ImageEditAgent()

    c1 = agent.run(_prior_candidate(), prompts, feedback="fix it")
    c2 = agent.run(_prior_candidate(), prompts, feedback="fix it again")

    assert c1.candidate_id != c2.candidate_id


def test_image_edit_agent_estimate_cost_is_zero():
    assert ImageEditAgent().estimate_cost() == 0.0
```

Also add to `tests/agents/test_protocols.py` — add this import line alongside the existing `from video_draft_pipeline.agents.image_agent import ImageAgent` line:

```python
from video_draft_pipeline.agents.image_edit_agent import ImageEditAgent
```

Add `ImageEditAgentProtocol` to the existing `from video_draft_pipeline.agents.protocols import (...)` block (alphabetical, matching the existing ordering: `DirectorAgentProtocol, ImageAgentProtocol, ImageEditAgentProtocol, PlanningAgentProtocol, ...`).

Add this test function at the end of the file:

```python
def test_image_edit_agents_satisfy_protocol():
    assert isinstance(ImageEditAgent(), ImageEditAgentProtocol)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_image_edit_agent.py tests/agents/test_protocols.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.image_edit_agent'` (and `ImportError` on `ImageEditAgentProtocol`).

- [ ] **Step 3: Add `ImageEditAgentProtocol`**

In `src/video_draft_pipeline/agents/protocols.py`, add this class after `ImageAgentProtocol` (the file already imports `Candidate` and `Prompts` at the top — no new imports needed):

```python
@runtime_checkable
class ImageEditAgentProtocol(Protocol):
    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate: ...
    def estimate_cost(self) -> float: ...
```

- [ ] **Step 4: Create the stub `ImageEditAgent`**

Create `src/video_draft_pipeline/agents/image_edit_agent.py`:

```python
import uuid

from ..schema import Candidate, Prompts


class ImageEditAgent:
    def __init__(self, model_name: str = "gemini-2.5-flash-image"):
        self.model_name = model_name

    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate:
        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        return Candidate(
            candidate_id=candidate_id,
            image_url=f"stub://{self.model_name}/{candidate_id}.png",
            generated_by=self.model_name,
        )

    def estimate_cost(self) -> float:
        return 0.0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/agents/test_image_edit_agent.py tests/agents/test_protocols.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/protocols.py src/video_draft_pipeline/agents/image_edit_agent.py tests/agents/test_image_edit_agent.py tests/agents/test_protocols.py
git commit -m "feat: add ImageEditAgentProtocol and stub ImageEditAgent"
```

---

### Task 2: `PromptAgentProtocol` gains `feedback`, stub `PromptAgent` accepts it

**Files:**
- Modify: `src/video_draft_pipeline/agents/protocols.py`
- Modify: `src/video_draft_pipeline/agents/prompt_agent.py`
- Modify: `tests/agents/test_prompt_agent.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `PromptAgentProtocol.run(self, scene: Scene, feedback: str | None = None) -> Prompts`. Stub `PromptAgent.run` accepts and ignores `feedback`.

- [ ] **Step 1: Write the failing test**

Add to `tests/agents/test_prompt_agent.py`:

```python
def test_prompt_agent_accepts_and_ignores_feedback():
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

    with_feedback = PromptAgent().run(scene, feedback="fix the lighting")
    without_feedback = PromptAgent().run(scene)

    assert with_feedback == without_feedback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_prompt_agent.py::test_prompt_agent_accepts_and_ignores_feedback -v`
Expected: FAIL with `TypeError: run() got an unexpected keyword argument 'feedback'`

- [ ] **Step 3: Update the protocol and the stub**

In `src/video_draft_pipeline/agents/protocols.py`, change `PromptAgentProtocol`:

```python
@runtime_checkable
class PromptAgentProtocol(Protocol):
    def run(self, scene: Scene, feedback: str | None = None) -> Prompts: ...
    def estimate_cost(self) -> float: ...
```

In `src/video_draft_pipeline/agents/prompt_agent.py`, change the `run` signature:

```python
    def run(self, scene: Scene, feedback: str | None = None) -> Prompts:
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
git add src/video_draft_pipeline/agents/protocols.py src/video_draft_pipeline/agents/prompt_agent.py tests/agents/test_prompt_agent.py
git commit -m "feat: add optional feedback param to PromptAgentProtocol and stub PromptAgent"
```

---

### Task 3: `OpenAIPromptAgent` threads `feedback` into its prompt-revision call

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_prompt_agent.py`
- Modify: `tests/agents/test_openai_prompt_agent.py`

**Interfaces:**
- Consumes: `PromptAgentProtocol.run(self, scene, feedback=None)` signature from Task 2.
- Produces: `_build_messages(scene: Scene, feedback: str | None = None) -> list[dict]`, `OpenAIPromptAgent.run(self, scene, feedback=None) -> Prompts` (feedback threaded into the LLM call when present).

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_prompt_agent.py`:

```python
def test_build_messages_includes_feedback_when_present():
    messages = _build_messages(_scene(), feedback="fix the lighting")
    user_content = messages[1]["content"]

    assert "fix the lighting" in user_content


def test_build_messages_omits_feedback_section_when_none():
    messages = _build_messages(_scene(), feedback=None)
    user_content = messages[1]["content"]

    assert "director" not in user_content.lower()


def test_run_passes_feedback_into_built_messages(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    scene = _scene()
    parsed = Prompts(image_prompt="p", video_motion_prompt="m")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(parsed=parsed)
    agent = OpenAIPromptAgent(client=client)

    agent.run(scene, feedback="fix the lighting")

    _, kwargs = client.chat.completions.parse.call_args
    assert kwargs["messages"] == _build_messages(scene, feedback="fix the lighting")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: FAIL — `_build_messages()` doesn't accept `feedback` yet (`TypeError`).

- [ ] **Step 3: Implement**

In `src/video_draft_pipeline/agents/openai_prompt_agent.py`, replace `_build_messages` and `run`:

```python
def _build_messages(scene: Scene, feedback: str | None = None) -> list[dict]:
    sb = scene.storyboard
    system = (
        "You are a prompt engineer generating an image generation prompt and a "
        "video motion prompt for a single scene of a game marketing video. "
        "image_prompt should describe the visual content: setting, subject, "
        "action, and camera framing. video_motion_prompt should describe only "
        "the camera movement and action, not static visual details. Respond "
        "in Korean, matching the language of the input."
    )
    user = (
        f"Camera: {sb.camera}\n"
        f"Subject: {sb.subject}\n"
        f"Action: {sb.action}\n"
        f"Setting: {sb.setting}"
    )
    if feedback:
        user += (
            f"\n\nThe previous attempt was rejected with this feedback from the "
            f"director — revise the prompts to address it: {feedback}"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

```python
    def run(self, scene: Scene, feedback: str | None = None) -> Prompts:
        parsed = self._structured_completion(_build_messages(scene, feedback), Prompts)
        image_prompt = parsed.image_prompt
        if scene.storyboard.required_elements:
            image_prompt = f"{image_prompt}, {', '.join(scene.storyboard.required_elements)}"
        return Prompts(
            image_prompt=image_prompt,
            video_motion_prompt=parsed.video_motion_prompt,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: PASS (all tests, including the pre-existing ones — `_build_messages(scene)` calls in older tests still work since `feedback` defaults to `None`).

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_prompt_agent.py tests/agents/test_openai_prompt_agent.py
git commit -m "feat: thread director feedback into OpenAIPromptAgent's revision prompt"
```

---

### Task 4: Orchestrator retry-branch wiring

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `ImageEditAgentProtocol` (Task 1), `PromptAgentProtocol.run(scene, feedback=None)` (Task 2).
- Produces: `run_pipeline(..., image_edit_agent: ImageEditAgentProtocol | None = None, ...)`. Internal helper `_generate_candidate(scene, prompt_agent, image_agent, image_edit_agent, running_cost, max_budget_usd) -> tuple[Candidate, float]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orchestrator.py` (these reuse the file's existing imports — `DirectorDecision`, `Candidate`, `Prompts`, `ProjectInput` are already imported at the top):

```python
class CountingScratchImageAgent:
    def __init__(self):
        self.calls = []

    def run(self, prompts):
        self.calls.append(prompts)
        return Candidate(
            candidate_id=f"cand_scratch_{len(self.calls)}", image_url="fake://scratch", generated_by="fake-image-model"
        )

    def estimate_cost(self):
        return 0.0


class CountingImageEditAgent:
    def __init__(self):
        self.calls = []

    def run(self, candidate, prompts, feedback):
        self.calls.append((candidate, prompts, feedback))
        return Candidate(candidate_id="cand_edit_1", image_url="fake://edit", generated_by="fake-edit-model")

    def estimate_cost(self):
        return 0.0


class FeedbackRevisingPromptAgent:
    def __init__(self):
        self.calls = []

    def run(self, scene, feedback=None):
        self.calls.append(feedback)
        return Prompts(image_prompt=f"revised-for:{feedback}", video_motion_prompt="revised-motion")

    def estimate_cost(self):
        return 0.0


class ScriptedDirectorAgent:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.call_count = 0

    def run(self, scene, review):
        decision = self.decisions[self.call_count]
        self.call_count += 1
        return decision

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_edits_on_first_retry_then_regenerates_from_scratch_on_second():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    image_agent = CountingScratchImageAgent()
    image_edit_agent = CountingImageEditAgent()
    prompt_agent = FeedbackRevisingPromptAgent()
    director_agent = ScriptedDirectorAgent(
        [
            DirectorDecision(decision="regenerate", feedback="fix the lighting", decided_by="fake-director"),
            DirectorDecision(decision="regenerate", feedback="still too dark", decided_by="fake-director"),
            DirectorDecision(decision="accept", decided_by="fake-director"),
        ]
    )

    project = run_pipeline(
        project_input,
        prompt_agent=prompt_agent,
        image_agent=image_agent,
        image_edit_agent=image_edit_agent,
        director_agent=director_agent,
    )

    scene = project.scenes[0]
    assert len(image_agent.calls) == 2  # attempt 1 (fresh) + attempt 3 (regenerate-from-scratch)
    assert len(image_edit_agent.calls) == 1  # attempt 2 only
    edited_candidate, _, edited_feedback = image_edit_agent.calls[0]
    assert edited_candidate.candidate_id == scene.candidates[0].candidate_id
    assert edited_feedback == "fix the lighting"
    assert prompt_agent.calls == [None, "still too dark"]  # initial call (no feedback) + fallback revision
    assert scene.prompts.image_prompt == "revised-for:still too dark"
    assert scene.retry_count == 2
    assert scene.accepted_candidate_id == scene.candidates[-1].candidate_id


def test_run_pipeline_defaults_image_edit_agent_to_stub_on_first_retry():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    director_agent = ScriptedDirectorAgent(
        [
            DirectorDecision(decision="regenerate", feedback="fix it", decided_by="fake-director"),
            DirectorDecision(decision="accept", decided_by="fake-director"),
        ]
    )

    project = run_pipeline(project_input, director_agent=director_agent)

    edited_candidate = project.scenes[0].candidates[1]
    assert edited_candidate.image_url.startswith("stub://gemini-2.5-flash-image/")


class FakeImageEditAgent:
    def run(self, candidate, prompts, feedback):
        return Candidate(candidate_id="fake_cand_edited", image_url="fake://edited", generated_by="fake-edit-model")

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_image_edit_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )
    director_agent = ScriptedDirectorAgent(
        [
            DirectorDecision(decision="regenerate", feedback="fix it", decided_by="fake-director"),
            DirectorDecision(decision="accept", decided_by="fake-director"),
        ]
    )

    project = run_pipeline(
        project_input, director_agent=director_agent, image_edit_agent=FakeImageEditAgent()
    )

    edited_candidate = project.scenes[0].candidates[1]
    assert edited_candidate.candidate_id == "fake_cand_edited"
    assert edited_candidate.generated_by == "fake-edit-model"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v -k "edit or edits_on_first"`
Expected: FAIL — `run_pipeline()` doesn't accept `image_edit_agent` yet (`TypeError`), and attempt 2 currently calls `image_agent.run` again instead of an edit agent.

- [ ] **Step 3: Implement the orchestrator change**

In `src/video_draft_pipeline/orchestrator.py`, update the schema import line (currently `from .schema import BeatId, Project, ProjectInput`) to:

```python
from .schema import BeatId, Candidate, Project, ProjectInput, Scene
```

Add these imports alongside the existing agent imports:

```python
from .agents.image_edit_agent import ImageEditAgent
```

Update the protocols import block to add `ImageEditAgentProtocol`:

```python
from .agents.protocols import (
    DirectorAgentProtocol,
    ImageAgentProtocol,
    ImageEditAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    ReviewAgentProtocol,
    StoryboardAgentProtocol,
)
```

Add a new module-level helper, placed just above `run_pipeline`:

```python
def _generate_candidate(
    scene: Scene,
    prompt_agent: PromptAgentProtocol,
    image_agent: ImageAgentProtocol,
    image_edit_agent: ImageEditAgentProtocol,
    running_cost: float,
    max_budget_usd: float,
) -> tuple[Candidate, float]:
    if scene.retry_count == 0:
        running_cost = _charge(running_cost, image_agent.estimate_cost(), max_budget_usd)
        return image_agent.run(scene.prompts), running_cost

    feedback = scene.candidates[-1].director_decision.feedback or ""

    if scene.retry_count == 1:
        running_cost = _charge(running_cost, image_edit_agent.estimate_cost(), max_budget_usd)
        return image_edit_agent.run(scene.candidates[-1], scene.prompts, feedback), running_cost

    running_cost = _charge(running_cost, prompt_agent.estimate_cost(), max_budget_usd)
    scene.prompts = prompt_agent.run(scene, feedback=feedback)
    running_cost = _charge(running_cost, image_agent.estimate_cost(), max_budget_usd)
    return image_agent.run(scene.prompts), running_cost
```

In `run_pipeline`'s signature, add the new param right after `image_agent`:

```python
    image_agent: ImageAgentProtocol | None = None,
    image_edit_agent: ImageEditAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
```

In the default-construction block, add right after `image_agent = image_agent or ImageAgent(models.image_model)`:

```python
    image_edit_agent = image_edit_agent or ImageEditAgent()
```

Replace the loop's current candidate-generation lines:

```python
            running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
            candidate = image_agent.run(scene.prompts)
            running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
```

with:

```python
            candidate, running_cost = _generate_candidate(
                scene, prompt_agent, image_agent, image_edit_agent, running_cost, project_input.max_budget_usd
            )
            running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v -k "edit or edits_on_first"`
Expected: PASS

- [ ] **Step 5: Run the full existing orchestrator suite to check for regressions**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS — all pre-existing tests (budget-blocking, injected-agent-override, real-agent-acceptance, assembly) must still pass unmodified. If any budget-blocking test fails, re-check the attempt/charge sequence against the failing test's math before changing test expectations — the existing partial-retry budget tests are expected to keep passing because injected "counting" agents in those tests aren't wired as `image_edit_agent`, so the edit-branch attempt silently uses the free default stub in those specific tests.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: PASS (this also catches any other file referencing `run_pipeline`'s old signature or `PromptAgentProtocol`'s old signature).

- [ ] **Step 7: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire director feedback into a fixed edit-then-regenerate retry schedule"
```

---

### Task 5: Real `GeminiImageEditAgent`

Real call shape confirmed against Google's actual docs (pasted by the user 2026-08-01): image editing uses the same `client.interactions.create()` method `GeminiReviewAgent` already calls (`agents/gemini_review_agent.py`), just with a plain multi-modal `input` list (text + image, no `response_format` needed for a single-shot edit) and the result read from `interaction.output_image.data` (base64) instead of `interaction.output_text`. Model stays `google/gemini-2.5-flash-image` (not the newer `gemini-3.1-flash-image`) — confirmed with the user: Elice hasn't granted access to the newer model yet, and Elice's API keys are free/sponsored, not billed per-call. Real per-image cost confirmed from Google's public pricing page: output images up to 1024×1024px consume 1290 tokens at $30/1M tokens = **$0.039/image**.

**Files:**
- Modify: `src/video_draft_pipeline/config.py`
- Create: `src/video_draft_pipeline/agents/gemini_image_edit_agent.py`
- Create: `tests/agents/test_gemini_image_edit_agent.py`
- Modify: `src/video_draft_pipeline/agents/factory.py`
- Modify: `tests/agents/test_factory.py`
- Modify: `tests/agents/test_protocols.py`

**Interfaces:**
- Consumes: `ImageEditAgentProtocol` (Task 1), `BaseGeminiAgent.__init__` (existing, unchanged — `agents/gemini_agent_base.py`).
- Produces: `GeminiImageEditAgent(model_name="google/gemini-2.5-flash-image", output_dir="media", api_key=None, client=None, base_url=None)` implementing `ImageEditAgentProtocol`. `factory.build_real_agents()` gains an `"image_edit_agent"` key.

- [ ] **Step 1: Add `image_edit_base_url` to config**

In `src/video_draft_pipeline/config.py`, add to `ApiKeys`:

```python
    image_edit_base_url: str | None = None
```

Add to `load_api_keys()`'s return statement:

```python
        image_edit_base_url=os.environ.get("GEMINI_IMAGE_EDIT_BASE_URL"),
```

- [ ] **Step 2: Write the failing tests**

Create `tests/agents/test_gemini_image_edit_agent.py`:

```python
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_image_edit_agent import GeminiImageEditAgent, ImageEditAgentError
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import Candidate, Prompts


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiImageEditAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_gemini_2_5_flash_image(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock())

    assert agent.model_name == "google/gemini-2.5-flash-image"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(model_name="custom-editor", client=MagicMock())

    assert agent.model_name == "custom-editor"


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.039
    assert agent.estimate_cost() == GeminiImageEditAgent.ESTIMATED_COST_USD


def _fake_interaction(output_image_b64: str) -> SimpleNamespace:
    return SimpleNamespace(output_image=SimpleNamespace(data=output_image_b64))


def test_run_calls_sdk_with_feedback_and_prior_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    edited_b64 = base64.b64encode(b"edited-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(edited_b64)
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(candidate, prompts, feedback="fix the lighting")

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "google/gemini-2.5-flash-image"
    input_content = kwargs["input"]
    assert input_content[0]["type"] == "text"
    assert "fix the lighting" in input_content[0]["text"]
    assert "a haunted castle" in input_content[0]["text"]
    assert input_content[1]["type"] == "image"
    assert input_content[1]["mime_type"] == "image/png"
    assert base64.b64decode(input_content[1]["data"]) == b"prior-image-bytes"


def test_run_writes_edited_image_and_returns_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    edited_b64 = base64.b64encode(b"edited-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(edited_b64)
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(candidate, prompts, feedback="fix the lighting")

    assert result.generated_by == "google/gemini-2.5-flash-image"
    assert result.candidate_id != candidate.candidate_id
    assert Path(result.image_url).exists()
    assert Path(result.image_url).read_bytes() == b"edited-image-bytes"


def test_run_wraps_sdk_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageEditAgentError):
        agent.run(candidate, prompts, feedback="fix it")


def test_run_wraps_unreadable_image_path(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")
    candidate = Candidate(
        candidate_id="c1", image_url=str(tmp_path / "does-not-exist.png"), generated_by="gpt-image-2"
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageEditAgentError):
        agent.run(candidate, prompts, feedback="fix it")


def test_run_wraps_missing_output_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"prior-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(output_image=None)
    agent = GeminiImageEditAgent(client=client, output_dir=tmp_path / "media")
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageEditAgentError):
        agent.run(candidate, prompts, feedback="fix it")


def test_base_url_resolved_from_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("GEMINI_IMAGE_EDIT_BASE_URL", "https://elice.example/image-edit/v1")

    class _CapturingClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = GeminiImageEditAgent(output_dir=tmp_path / "media")

    assert agent._client.kwargs["http_options"] == {"base_url": "https://elice.example/image-edit/v1"}
```

- [ ] **Step 3: Implement `GeminiImageEditAgent`**

Create `src/video_draft_pipeline/agents/gemini_image_edit_agent.py`:

```python
import base64
import uuid
from pathlib import Path

from ..schema import Candidate, Prompts
from .gemini_agent_base import BaseGeminiAgent


class ImageEditAgentError(Exception):
    pass


class GeminiImageEditAgent(BaseGeminiAgent):
    error_cls = ImageEditAgentError
    ESTIMATED_COST_USD = 0.039
    base_url_config_field = "image_edit_base_url"

    def __init__(
        self,
        model_name: str = "google/gemini-2.5-flash-image",
        output_dir: str | Path = "media",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate:
        try:
            image_bytes = Path(candidate.image_url).read_bytes()
        except OSError as exc:
            raise self.error_cls(f"Could not read candidate image at {candidate.image_url!r}: {exc}") from exc
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        input_content = [
            {
                "type": "text",
                "text": (
                    "Edit this AI-generated image for a game marketing video scene to address "
                    f"the following director feedback: {feedback}\n"
                    f"Keep the edit consistent with the original prompt: {prompts.image_prompt}"
                ),
            },
            {"type": "image", "data": image_b64, "mime_type": "image/png"},
        ]

        try:
            interaction = self._client.interactions.create(model=self.model_name, input=input_content)
        except Exception as exc:
            raise self.error_cls(f"Gemini image-edit call failed: {exc}") from exc

        if interaction.output_image is None:
            raise self.error_cls("Gemini image-edit call returned no output image")

        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        edited_bytes = base64.b64decode(interaction.output_image.data)
        file_path = self.output_dir / f"{candidate_id}.png"
        file_path.write_bytes(edited_bytes)

        return Candidate(
            candidate_id=candidate_id,
            image_url=str(file_path),
            generated_by=self.model_name,
        )

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_gemini_image_edit_agent.py -v`
Expected: PASS

- [ ] **Step 5: Wire into `factory.py`**

In `src/video_draft_pipeline/agents/factory.py`, add the import:

```python
from .gemini_image_edit_agent import GeminiImageEditAgent
```

Add to `build_real_agents`'s return dict:

```python
        "image_edit_agent": GeminiImageEditAgent(
            models.image_edit_model, output_dir=output_dir, api_key=gemini_api_key, client=gemini_client
        ),
```

- [ ] **Step 6: Update factory and protocol tests**

In `tests/agents/test_factory.py`, update `test_returns_exactly_the_six_expected_keys` (rename to `test_returns_exactly_the_seven_expected_keys`) to add `"image_edit_agent"` to the expected set, and add `"image_edit_agent"` assertions to `test_explicit_api_key_threaded_to_all_agents` and `test_custom_model_config_threaded_to_each_agent` (following the existing `review_agent`/`gemini_api_key` pattern for each).

In `tests/agents/test_protocols.py`, `test_image_edit_agents_satisfy_protocol` (from Task 1) needs a `tmp_path` param added to its signature (since `GeminiImageEditAgent`, like `OpenAIImageAgent`, requires an `output_dir`):

```python
def test_image_edit_agents_satisfy_protocol(tmp_path):
    assert isinstance(ImageEditAgent(), ImageEditAgentProtocol)
    assert isinstance(
        GeminiImageEditAgent(api_key="test-key", output_dir=tmp_path / "media"), ImageEditAgentProtocol
    )
```

(with the corresponding `GeminiImageEditAgent` import added at the top of the file, alongside the existing `from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent` line).

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/video_draft_pipeline/config.py src/video_draft_pipeline/agents/gemini_image_edit_agent.py tests/agents/test_gemini_image_edit_agent.py src/video_draft_pipeline/agents/factory.py tests/agents/test_factory.py tests/agents/test_protocols.py
git commit -m "feat: add real GeminiImageEditAgent and wire it into build_real_agents"
```
