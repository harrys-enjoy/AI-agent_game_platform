# Real ReviewAgent (Gemini) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `ReviewAgent` a real, Gemini-backed implementation (`GeminiReviewAgent`) that judges a generated image against its prompt, extend its signature so it actually receives criteria to judge against, and wire it into `run_pipeline`'s injection/budget/factory machinery exactly like the other 4 real agents.

**Architecture:** A new `BaseGeminiAgent` (mirroring `BaseOpenAIAgent`, backed by the `google-genai` SDK) underlies `GeminiReviewAgent`. `ReviewAgent`'s `run()` signature grows a third parameter (`prompts: Prompts`) so it has something to judge the image against — this touches the stub, the protocol, and the orchestrator's call site. `run_pipeline` gets a `review_agent` injection parameter and budget guard, following the exact pattern already used for the other 4 agents. `build_real_agents()` grows a `review_agent` entry and its `api_key`/`client` parameters are renamed to `openai_api_key`/`openai_client` with `gemini_api_key`/`gemini_client` added alongside, since a second provider now exists.

**Tech Stack:** Python 3.11+, Pydantic v2, `google-genai>=2.15` (new dependency), `unittest.mock.MagicMock`, pytest.

## Global Constraints

- `GeminiReviewAgent.ESTIMATED_COST_USD = 0.02`. `GeminiReviewAgent`'s default `model_name = "gemini-3-pro-image"`, matching `config.ModelConfig.review_model`'s existing default exactly — no departure.
- `prior_candidates` stays in `ReviewAgentProtocol`'s signature but is not sent to Gemini in this plan — v1 only checks prompt-fidelity for the current candidate.
- `MissingAPIKeyError` is reused from `agents/openai_agent_base.py` — do not define a duplicate exception.
- The image-agent and review-agent budget guards must both run fresh on every retry attempt inside the scene loop, not just once per scene. The existing render-cost guard is untouched.
- `DirectorAgent` and `VideoRenderAgent`/`VeoBackend` are out of scope — they remain stubs, untouched, and are not added to `run_pipeline`'s injection parameters or `build_real_agents()` in this plan.
- `build_real_agents()`'s `api_key`/`client` parameters are renamed to `openai_api_key`/`openai_client`; this is a deliberate breaking rename of a just-shipped function, not an oversight.
- No live-API or integration tests against the real Gemini or OpenAI APIs. All tests use `MagicMock()` clients.
- All existing tests must keep passing (164 as of the last branch) except where this plan explicitly updates them (the `FailingReviewAgent` test doubles' signatures, `test_factory.py`'s renamed parameters).

---

### Task 1: Gemini agent base + `GeminiReviewAgent`

**Files:**
- Modify: `pyproject.toml`
- Create: `src/video_draft_pipeline/agents/gemini_agent_base.py`
- Create: `src/video_draft_pipeline/agents/gemini_review_agent.py`
- Test: `tests/agents/test_gemini_agent_base.py`
- Test: `tests/agents/test_gemini_review_agent.py`

**Interfaces:**
- Consumes: `config.load_api_keys().gemini_api_key` (already exists in `src/video_draft_pipeline/config.py`), `MissingAPIKeyError` (from `agents/openai_agent_base.py`, already exists), `schema.Candidate`, `schema.ConsistencyReview`, `schema.Prompts` (already exist).
- Produces: `BaseGeminiAgent(model_name, api_key=None, client=None)` with `_structured_interaction(input_content, response_schema) -> BaseModel`, in `video_draft_pipeline.agents.gemini_agent_base`. `GeminiReviewAgent(model_name="gemini-3-pro-image", api_key=None, client=None)` with `run(candidate, prior_candidates, prompts) -> ConsistencyReview` and `estimate_cost() -> float`, plus `ReviewAgentError` and `ReviewVerdict`, in `video_draft_pipeline.agents.gemini_review_agent`. Tasks 2-4 do not consume these directly (they only need the class to exist for wiring), but Task 3's orchestrator tests and Task 4's factory both construct `GeminiReviewAgent` instances.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_gemini_agent_base.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from video_draft_pipeline.agents.gemini_agent_base import BaseGeminiAgent
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError


class _DummyError(Exception):
    pass


class _DummyAgent(BaseGeminiAgent):
    error_cls = _DummyError


class _DummyResult(BaseModel):
    value: str


def _fake_interaction(output_text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=output_text)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        _DummyAgent(model_name="dummy-model")


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", client=MagicMock())

    assert agent.api_key == "env-key"


def test_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", client=MagicMock())

    assert agent.model_name == "dummy-model"


def test_structured_interaction_returns_parsed_result(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"value": "the-result"}')
    agent = _DummyAgent(model_name="dummy-model", client=client)

    result = agent._structured_interaction(input_content=[], response_schema=_DummyResult)

    assert result == _DummyResult(value="the-result")


def test_structured_interaction_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = _DummyAgent(model_name="dummy-model", client=client)

    with pytest.raises(_DummyError):
        agent._structured_interaction(input_content=[], response_schema=_DummyResult)


def test_structured_interaction_wraps_malformed_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = _DummyAgent(model_name="dummy-model", client=client)

    with pytest.raises(_DummyError):
        agent._structured_interaction(input_content=[], response_schema=_DummyResult)
```

Create `tests/agents/test_gemini_review_agent.py`:

```python
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent, ReviewAgentError
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import Candidate, Prompts


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiReviewAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_gemini_3_pro_image(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.model_name == "gemini-3-pro-image"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(model_name="custom-reviewer", client=MagicMock())

    assert agent.model_name == "custom-reviewer"


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.02
    assert agent.estimate_cost() == GeminiReviewAgent.ESTIMATED_COST_USD


def _fake_interaction(output_text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=output_text)


def test_run_calls_sdk_with_prompt_and_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"passed": true, "issues": []}')
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(candidate, prior_candidates=[], prompts=prompts)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "gemini-3-pro-image"
    input_content = kwargs["input"]
    assert input_content[0]["type"] == "text"
    assert "a haunted castle" in input_content[0]["text"]
    assert input_content[1]["type"] == "image"
    assert input_content[1]["mime_type"] == "image/png"
    assert base64.b64decode(input_content[1]["data"]) == b"fake-image-bytes"


def test_run_returns_consistency_review_from_passing_verdict(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"passed": true, "issues": []}')
    agent = GeminiReviewAgent(model_name="custom-reviewer", client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    review = agent.run(candidate, prior_candidates=[], prompts=prompts)

    assert review.reviewed_by == "custom-reviewer"
    assert review.passed is True
    assert review.issues == []


def test_run_returns_consistency_review_from_failing_verdict(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(
        '{"passed": false, "issues": ["wrong subject"]}'
    )
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    review = agent.run(candidate, prior_candidates=[], prompts=prompts)

    assert review.passed is False
    assert review.issues == ["wrong subject"]


def test_run_wraps_sdk_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ReviewAgentError):
        agent.run(candidate, prior_candidates=[], prompts=prompts)


def test_run_wraps_malformed_json_output(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ReviewAgentError):
        agent.run(candidate, prior_candidates=[], prompts=prompts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_gemini_agent_base.py tests/agents/test_gemini_review_agent.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.gemini_agent_base'` (both files fail at collection, since neither module exists yet).

- [ ] **Step 3: Add the dependency and write the implementation**

In `pyproject.toml`, change:

```toml
dependencies = [
    "pydantic>=2.5",
    "openai>=1.92",
]
```

to:

```toml
dependencies = [
    "pydantic>=2.5",
    "openai>=1.92",
    "google-genai>=2.15",
]
```

Then run `pip install -e ".[dev]"` from the repo root to install the new dependency into the active environment.

Create `src/video_draft_pipeline/agents/gemini_agent_base.py`:

```python
from google import genai
from pydantic import BaseModel

from .. import config
from .openai_agent_base import MissingAPIKeyError


class BaseGeminiAgent:
    error_cls: type[Exception]

    def __init__(self, model_name: str, api_key: str | None = None, client: genai.Client | None = None):
        resolved_key = api_key or config.load_api_keys().gemini_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No Gemini API key found: pass api_key explicitly or set GEMINI_API_KEY."
            )
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or genai.Client(api_key=resolved_key)

    def _structured_interaction(self, input_content: list[dict], response_schema: type[BaseModel]) -> BaseModel:
        try:
            interaction = self._client.interactions.create(
                model=self.model_name,
                input=input_content,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema.model_json_schema(),
                },
            )
        except Exception as exc:
            raise self.error_cls(f"Gemini call failed: {exc}") from exc
        try:
            return response_schema.model_validate_json(interaction.output_text)
        except Exception as exc:
            raise self.error_cls(f"Gemini call returned unparseable output: {exc}") from exc
```

Create `src/video_draft_pipeline/agents/gemini_review_agent.py`:

```python
import base64
from pathlib import Path

from pydantic import BaseModel

from ..schema import Candidate, ConsistencyReview, Prompts
from .gemini_agent_base import BaseGeminiAgent


class ReviewAgentError(Exception):
    pass


class ReviewVerdict(BaseModel):
    passed: bool
    issues: list[str]


class GeminiReviewAgent(BaseGeminiAgent):
    error_cls = ReviewAgentError
    ESTIMATED_COST_USD = 0.02

    def __init__(self, model_name: str = "gemini-3-pro-image", api_key: str | None = None, client=None):
        super().__init__(model_name, api_key, client)

    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
        image_bytes = Path(candidate.image_url).read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        input_content = [
            {
                "type": "text",
                "text": (
                    "You are reviewing an AI-generated image for a game marketing video scene. "
                    f"The image was generated from this prompt: {prompts.image_prompt}\n"
                    "Judge whether the image faithfully matches the prompt. Respond with passed=true "
                    "only if the image clearly matches; otherwise passed=false and list concrete issues."
                ),
            },
            {"type": "image", "data": image_b64, "mime_type": "image/png"},
        ]

        verdict = self._structured_interaction(input_content, ReviewVerdict)
        return ConsistencyReview(reviewed_by=self.model_name, passed=verdict.passed, issues=verdict.issues)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_gemini_agent_base.py tests/agents/test_gemini_review_agent.py -v`

Expected: PASS (7 + 12 = 19 passed).

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`

Expected: all tests pass, zero failures (previous total was 164; this task adds 19, so expect 183 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/video_draft_pipeline/agents/gemini_agent_base.py src/video_draft_pipeline/agents/gemini_review_agent.py tests/agents/test_gemini_agent_base.py tests/agents/test_gemini_review_agent.py
git commit -m "feat: add google-genai dependency and real GeminiReviewAgent"
```

---

### Task 2: Protocol + stub signature extension

**Files:**
- Modify: `src/video_draft_pipeline/agents/protocols.py`
- Modify: `src/video_draft_pipeline/agents/review_agent.py`
- Test: `tests/agents/test_review_agent.py`
- Test: `tests/agents/test_protocols.py`

**Interfaces:**
- Consumes: `GeminiReviewAgent` (Task 1, for the protocol conformance test).
- Produces: `ReviewAgentProtocol` (in `video_draft_pipeline.agents.protocols`) with `run(candidate, prior_candidates, prompts) -> ConsistencyReview` and `estimate_cost() -> float`. `ReviewAgent.run(candidate, prior_candidates, prompts) -> ConsistencyReview` and `ReviewAgent.estimate_cost() -> float` (in `video_draft_pipeline.agents.review_agent`). Task 3 consumes `ReviewAgentProtocol` directly and calls the new 3-arg `run()` signature at the orchestrator's call site.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/agents/test_review_agent.py` with:

```python
from video_draft_pipeline.agents.review_agent import ReviewAgent
from video_draft_pipeline.schema import Candidate, Prompts


def test_review_agent_stub_always_passes_with_no_issues():
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    review = ReviewAgent(reviewer_name="gemini-3-pro-image").run(
        candidate, prior_candidates=[], prompts=prompts
    )

    assert review.reviewed_by == "gemini-3-pro-image"
    assert review.passed is True
    assert review.issues == []


def test_review_agent_estimate_cost_is_zero():
    assert ReviewAgent().estimate_cost() == 0.0
```

Append to `tests/agents/test_protocols.py` (add the two new imports alongside the existing ones, and the new test function):

```python
from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent
from video_draft_pipeline.agents.review_agent import ReviewAgent
```

```python
def test_review_agents_satisfy_protocol():
    assert isinstance(ReviewAgent(), ReviewAgentProtocol)
    assert isinstance(GeminiReviewAgent(api_key="test-key"), ReviewAgentProtocol)
```

Also add `ReviewAgentProtocol` to the existing `from video_draft_pipeline.agents.protocols import (...)` import block in `tests/agents/test_protocols.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_review_agent.py tests/agents/test_protocols.py -v`

Expected: FAIL — `test_review_agent_stub_always_passes_with_no_issues` fails with `TypeError: ReviewAgent.run() got an unexpected keyword argument 'prompts'`; `test_review_agent_estimate_cost_is_zero` fails with `AttributeError`; `test_review_agents_satisfy_protocol` fails with `ImportError: cannot import name 'ReviewAgentProtocol'`.

- [ ] **Step 3: Write the implementation**

Append to `src/video_draft_pipeline/agents/protocols.py` (add `ConsistencyReview` to the existing `from ..schema import ...` line):

```python
@runtime_checkable
class ReviewAgentProtocol(Protocol):
    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview: ...
    def estimate_cost(self) -> float: ...
```

Replace the full contents of `src/video_draft_pipeline/agents/review_agent.py` with:

```python
from ..schema import Candidate, ConsistencyReview, Prompts


class ReviewAgent:
    def __init__(self, reviewer_name: str = "gemini-3-pro-image"):
        self.reviewer_name = reviewer_name

    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
        return ConsistencyReview(reviewed_by=self.reviewer_name, passed=True, issues=[])

    def estimate_cost(self) -> float:
        return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_review_agent.py tests/agents/test_protocols.py -v`

Expected: PASS (2 + 6 = 8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/protocols.py src/video_draft_pipeline/agents/review_agent.py tests/agents/test_review_agent.py tests/agents/test_protocols.py
git commit -m "feat: extend ReviewAgent signature with prompts, add ReviewAgentProtocol"
```

---

### Task 3: Orchestrator wiring

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `ReviewAgentProtocol` (Task 2), `GeminiReviewAgent` (Task 1).
- Produces: `run_pipeline(..., review_agent: ReviewAgentProtocol | None = None) -> Project` — one more optional keyword parameter, same pattern as the other 4. No new public interface beyond this.

- [ ] **Step 1: Write the failing tests**

In `tests/test_orchestrator.py`, fix the two existing `FailingReviewAgent` nested classes (both currently override `run` with the old 2-arg signature; both need the third `prompts` parameter added so they keep matching once the orchestrator calls `run()` with 3 arguments).

Change (inside `test_run_pipeline_raises_when_review_always_fails`):

```python
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate: Candidate, prior_candidates: list[Candidate]) -> ConsistencyReview:
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )
```

to:

```python
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )
```

Change (inside `test_run_pipeline_blocks_image_agent_partway_through_retries`):

```python
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate, prior_candidates):
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )
```

to:

```python
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate, prior_candidates, prompts):
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )
```

Then append these 3 new tests to the end of `tests/test_orchestrator.py`:

```python
class FakeReviewAgent:
    def run(self, candidate, prior_candidates, prompts):
        return ConsistencyReview(
            reviewed_by="fake-reviewer", passed=True, issues=["fake-review-marker"]
        )

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_review_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, review_agent=FakeReviewAgent())

    candidate = project.scenes[0].candidates[-1]
    assert candidate.consistency_review.reviewed_by == "fake-reviewer"
    assert candidate.consistency_review.issues == ["fake-review-marker"]


class ExpensiveReviewAgent:
    def __init__(self):
        self.run_called = False

    def run(self, candidate, prior_candidates, prompts):
        self.run_called = True
        return ConsistencyReview(reviewed_by="expensive-reviewer", passed=True, issues=[])

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_review_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveReviewAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, review_agent=expensive_agent)

    assert expensive_agent.run_called is False


def test_run_pipeline_accepts_real_gemini_review_agent(tmp_path):
    from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent

    image_path = tmp_path / "media" / "cand_1.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-image-bytes")

    class FakeImageAgentWithRealFile:
        def run(self, prompts):
            return Candidate(
                candidate_id="cand_1", image_url=str(image_path), generated_by="fake-model"
            )

        def estimate_cost(self):
            return 0.0

    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_text='{"passed": true, "issues": []}'
    )
    real_review_agent = GeminiReviewAgent(api_key="test-key", client=client)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        image_agent=FakeImageAgentWithRealFile(),
        review_agent=real_review_agent,
    )

    candidate = project.scenes[0].candidates[-1]
    assert candidate.consistency_review.reviewed_by == "gemini-3-pro-image"
    assert candidate.consistency_review.passed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`

Expected: the 3 new tests FAIL — the injection/budget tests with `TypeError: run_pipeline() got an unexpected keyword argument 'review_agent'`; the real-agent test with the same. All other tests (including the two now-fixed `FailingReviewAgent` tests) still PASS, since those two fixes are pure signature updates matching the stub's already-passing 3-arg contract from Task 2.

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/orchestrator.py`, change the protocols import from:

```python
from .agents.protocols import (
    ImageAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    StoryboardAgentProtocol,
)
```

to:

```python
from .agents.protocols import (
    ImageAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    ReviewAgentProtocol,
    StoryboardAgentProtocol,
)
```

Change the `run_pipeline` signature and the `review_agent` construction line from:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
) -> Project:
    models = model_config or ModelConfig()
    project = Project(project_id=f"proj_{uuid.uuid4().hex[:8]}", input=project_input)

    planning_agent = planning_agent or PlanningAgent(models.planning_model)
    storyboard_agent = storyboard_agent or StoryboardAgent(models.storyboard_model)
    prompt_agent = prompt_agent or PromptAgent(models.prompt_model)
    image_agent = image_agent or ImageAgent(models.image_model)
    review_agent = ReviewAgent(models.review_model)
    director_agent = DirectorAgent(models.director_model)
```

to:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
) -> Project:
    models = model_config or ModelConfig()
    project = Project(project_id=f"proj_{uuid.uuid4().hex[:8]}", input=project_input)

    planning_agent = planning_agent or PlanningAgent(models.planning_model)
    storyboard_agent = storyboard_agent or StoryboardAgent(models.storyboard_model)
    prompt_agent = prompt_agent or PromptAgent(models.prompt_model)
    image_agent = image_agent or ImageAgent(models.image_model)
    review_agent = review_agent or ReviewAgent(models.review_model)
    director_agent = DirectorAgent(models.director_model)
```

Change the retry loop's guard/call sequence from:

```python
        max_attempts = scene.max_retries + 1
        for _ in range(max_attempts):
            running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
            candidate = image_agent.run(scene.prompts)
            candidate.consistency_review = review_agent.run(candidate, scene.candidates)
            candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
```

to:

```python
        max_attempts = scene.max_retries + 1
        for _ in range(max_attempts):
            running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
            candidate = image_agent.run(scene.prompts)
            running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.consistency_review = review_agent.run(candidate, scene.candidates, scene.prompts)
            candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
```

Everything else in `run_pipeline` is unchanged — `director_agent`/`render_backend` construction, guards, cost accumulation after render, and the rest of the retry/accept/reject logic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`

Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`

Expected: all tests pass, zero failures (previous total was 183 after Task 1/2; this task adds 3, so expect 186 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire review_agent injection and budget guard into run_pipeline"
```

---

### Task 4: Factory extension + README

**Files:**
- Modify: `src/video_draft_pipeline/agents/factory.py`
- Modify: `tests/agents/test_factory.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `GeminiReviewAgent` (Task 1), `run_pipeline`'s `review_agent` parameter (Task 3).
- Produces: `build_real_agents(openai_api_key=None, gemini_api_key=None, output_dir="media", model_config=None, openai_client=None, gemini_client=None) -> dict[str, object]` with a 5th key, `review_agent`. This is a breaking rename of the function's existing `api_key`/`client` parameters — no other task in this plan or prior plans consumes `build_real_agents` besides its own test file and the README, both updated in this task.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/agents/test_factory.py` with:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.agents.openai_storyboard_agent import SceneDraft, StoryboardDraft
from video_draft_pipeline.config import ModelConfig
from video_draft_pipeline.orchestrator import run_pipeline
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput, Prompts


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        build_real_agents(output_dir=tmp_path / "media", gemini_client=MagicMock())


def test_explicit_api_key_threaded_to_all_agents(tmp_path):
    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        output_dir=tmp_path / "media",
    )

    assert agents["planning_agent"].api_key == "explicit-openai-key"
    assert agents["storyboard_agent"].api_key == "explicit-openai-key"
    assert agents["prompt_agent"].api_key == "explicit-openai-key"
    assert agents["image_agent"].api_key == "explicit-openai-key"
    assert agents["review_agent"].api_key == "explicit-gemini-key"


def test_returns_exactly_the_five_expected_keys(tmp_path):
    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        output_dir=tmp_path / "media",
    )

    assert set(agents.keys()) == {
        "planning_agent",
        "storyboard_agent",
        "prompt_agent",
        "image_agent",
        "review_agent",
    }


def test_custom_model_config_threaded_to_each_agent(tmp_path):
    model_config = ModelConfig(
        planning_model="custom-planner",
        storyboard_model="custom-storyboarder",
        prompt_model="custom-prompter",
        image_model="custom-imager",
        review_model="custom-reviewer",
    )

    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        output_dir=tmp_path / "media",
        model_config=model_config,
    )

    assert agents["planning_agent"].model_name == "custom-planner"
    assert agents["storyboard_agent"].model_name == "custom-storyboarder"
    assert agents["prompt_agent"].model_name == "custom-prompter"
    assert agents["image_agent"].model_name == "custom-imager"
    assert agents["review_agent"].model_name == "custom-reviewer"


def test_output_dir_threaded_to_image_agent_only(tmp_path):
    custom_dir = tmp_path / "custom-media"

    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        output_dir=custom_dir,
    )

    assert agents["image_agent"].output_dir == custom_dir
    assert custom_dir.is_dir()


def test_build_real_agents_output_works_with_run_pipeline(tmp_path):
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )
    draft = StoryboardDraft(
        scenes=[
            SceneDraft(
                beat_id=beat_id,
                camera="cam",
                subject="subj",
                action="act",
                setting="set",
                required_elements=[],
                duration_weight=1,
            )
            for beat_id in ("setup", "conflict", "climax", "resolution")
        ]
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    def fake_parse(*, model, messages, response_format):
        if response_format is Narrative:
            parsed = narrative
        elif response_format is StoryboardDraft:
            parsed = draft
        elif response_format is Prompts:
            parsed = prompts
        else:
            raise AssertionError(f"unexpected response_format: {response_format}")
        message = SimpleNamespace(parsed=parsed, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    shared_openai_client = MagicMock()
    shared_openai_client.chat.completions.parse.side_effect = fake_parse
    image_data = SimpleNamespace(b64_json="ZmFrZS1pbWFnZS1ieXRlcw==")
    shared_openai_client.images.generate.return_value = SimpleNamespace(data=[image_data])

    shared_gemini_client = MagicMock()
    shared_gemini_client.interactions.create.return_value = SimpleNamespace(
        output_text='{"passed": true, "issues": []}'
    )

    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        **build_real_agents(
            openai_api_key="test-key",
            gemini_api_key="test-key",
            openai_client=shared_openai_client,
            gemini_client=shared_gemini_client,
            output_dir=tmp_path / "media",
        ),
    )

    assert len(project.scenes) == 4
    assert project.scenes[0].render is not None
    assert project.scenes[0].candidates[-1].consistency_review.passed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_factory.py -v`

Expected: FAIL — every test calling `build_real_agents(..., openai_api_key=..., gemini_api_key=..., openai_client=..., gemini_client=...)` fails with `TypeError: build_real_agents() got an unexpected keyword argument 'openai_api_key'` (the current function only accepts `api_key`/`client`).

- [ ] **Step 3: Write the implementation**

Replace the full contents of `src/video_draft_pipeline/agents/factory.py` with:

```python
from pathlib import Path

from google import genai
from openai import OpenAI

from ..config import ModelConfig
from .gemini_review_agent import GeminiReviewAgent
from .openai_image_agent import OpenAIImageAgent
from .openai_planning_agent import OpenAIPlanningAgent
from .openai_prompt_agent import OpenAIPromptAgent
from .openai_storyboard_agent import OpenAIStoryboardAgent


def build_real_agents(
    openai_api_key: str | None = None,
    gemini_api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    openai_client: OpenAI | None = None,
    gemini_client: genai.Client | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": OpenAIPlanningAgent(models.planning_model, api_key=openai_api_key, client=openai_client),
        "storyboard_agent": OpenAIStoryboardAgent(models.storyboard_model, api_key=openai_api_key, client=openai_client),
        "prompt_agent": OpenAIPromptAgent(models.prompt_model, api_key=openai_api_key, client=openai_client),
        "image_agent": OpenAIImageAgent(models.image_model, output_dir=output_dir, api_key=openai_api_key, client=openai_client),
        "review_agent": GeminiReviewAgent(models.review_model, api_key=gemini_api_key, client=gemini_client),
    }
```

In `README.md`, replace the entire `## Real agent injection` section (from that heading through the paragraph ending "...bypassed for any stage you inject (via either path above)." and stopping right before `## Test`) with:

```markdown
## Real agent injection

`run_pipeline` accepts `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, and `review_agent` — pass an instance of the matching real class to use it for that stage instead of the stub. Any not given fall back to their stub, so the pipeline stays fully offline by default. `DirectorAgent` and `VideoRenderAgent` have no real implementation yet and cannot be overridden this way.

The easiest way to inject all five at once is `build_real_agents()`, which constructs them with shared config and returns a dict shaped exactly for `run_pipeline`'s injection parameters:

```python
from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, **build_real_agents(openai_api_key="...", gemini_api_key="..."))
```

`build_real_agents` takes its own `model_config: ModelConfig` argument — it builds all 5 real agents from `ModelConfig()` defaults unless you pass one in. If you also want non-default models, pass the *same* `ModelConfig` to both `build_real_agents` and `run_pipeline`, or the two calls won't share model choices and some stages will silently use the wrong model:

```python
from video_draft_pipeline.config import ModelConfig

cfg = ModelConfig(planning_model="gpt-5.4", render_backend="veo-3.1-lite")
run_pipeline(
    project_input,
    model_config=cfg,
    **build_real_agents(openai_api_key="...", gemini_api_key="...", model_config=cfg),
)
```

To inject just one or two stages instead of all five, construct that agent directly (OpenAI-backed agents under `video_draft_pipeline.agents.openai_*`, the Gemini-backed reviewer under `video_draft_pipeline.agents.gemini_review_agent`):

```python
from video_draft_pipeline.agents.openai_planning_agent import OpenAIPlanningAgent
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, planning_agent=OpenAIPlanningAgent(api_key="..."))
```

An injected real agent's own `model_name` applies for that stage — `ModelConfig`'s corresponding field on `run_pipeline` is bypassed for any stage you inject (via either path above).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_factory.py -v`

Expected: PASS (6 passed).

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`

Expected: all tests pass, zero failures (previous total was 186 after Task 1-3; `test_factory.py` had 6 tests before this task and still has 6 after — same count, updated content — so the total stays 186 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/factory.py tests/agents/test_factory.py README.md
git commit -m "feat: add review_agent to build_real_agents, rename api_key/client params"
```

---

## Self-Review Notes

- **Spec coverage:** `BaseGeminiAgent`/`GeminiReviewAgent` (Gemini API shape, structured output, model default, cost constant) → Task 1. `ReviewAgentProtocol`, stub 3-arg signature, `estimate_cost` → Task 2. Orchestrator injection param, per-retry budget guard, call-site `prompts` threading, existing `FailingReviewAgent` fixes → Task 3. Factory extension, param rename, README update → Task 4. Non-goals (`DirectorAgent`/`VideoRenderAgent` untouched, `prior_candidates` not sent to Gemini, no live-API tests, no `ConsistencyReview.issues` schema change) — no task touches any of these.
- **Placeholder scan:** no TBD/TODO; every step has complete, runnable code; the two `FailingReviewAgent` fixes in Task 3 are each written out in full (not "same as above") since they're in different test functions.
- **Type consistency:** `run(candidate, prior_candidates, prompts) -> ConsistencyReview` matches exactly across `ReviewAgentProtocol` (Task 2), the stub `ReviewAgent` (Task 2), `GeminiReviewAgent` (Task 1), and every test double introduced in Task 3 (`FakeReviewAgent`, `ExpensiveReviewAgent`, both fixed `FailingReviewAgent`s). `estimate_cost() -> float` matches across all of the same. `build_real_agents`'s renamed parameters (`openai_api_key`, `openai_client`, `gemini_api_key`, `gemini_client`) are used consistently across Task 4's implementation, its test file, and the README.
