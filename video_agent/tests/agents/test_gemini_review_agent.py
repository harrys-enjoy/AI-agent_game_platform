import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent, ReviewAgentError
from video_draft_pipeline.agents.errors import MissingAPIKeyError
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


def test_default_model_name_is_gemini_3_6_flash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.6-flash"


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
    assert kwargs["model"] == "gemini-3.6-flash"
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


def test_run_wraps_unreadable_image_path(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    agent = GeminiReviewAgent(client=MagicMock())
    candidate = Candidate(
        candidate_id="c1", image_url=str(tmp_path / "does-not-exist.png"), generated_by="gpt-image-2"
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ReviewAgentError):
        agent.run(candidate, prior_candidates=[], prompts=prompts)


def test_run_sends_mime_type_matching_source_image_extension(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.jpg"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"passed": true, "issues": []}')
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(candidate, prior_candidates=[], prompts=prompts)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["input"][1]["mime_type"] == "image/jpeg"


def test_run_calls_sdk_with_hard_perspective_consistency_requirement(monkeypatch, tmp_path):
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
    text = kwargs["input"][0]["text"]
    assert "hard requirements" in text
    assert "Perspective consistency" in text


def test_run_calls_sdk_with_hard_physical_integrity_requirement(monkeypatch, tmp_path):
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
    text = kwargs["input"][0]["text"]
    assert "Physical integrity" in text
    assert "bent, kinked, melted, or disconnected" in text


def test_run_calls_sdk_with_defect_category_classification_instructions(monkeypatch, tmp_path):
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
    text = kwargs["input"][0]["text"]
    assert "defect_category" in text
    assert "localized_artifact" in text
    assert "structural_geometry" in text


def test_run_defaults_defect_category_to_none_when_verdict_omits_it(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction('{"passed": true, "issues": []}')
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    review = agent.run(candidate, prior_candidates=[], prompts=prompts)

    assert review.defect_category == "none"


def test_run_passes_through_localized_artifact_defect_category(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(
        '{"passed": false, "issues": ["stray mark"], "defect_category": "localized_artifact"}'
    )
    agent = GeminiReviewAgent(client=client)
    candidate = Candidate(candidate_id="c1", image_url=str(image_path), generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    review = agent.run(candidate, prior_candidates=[], prompts=prompts)

    assert review.defect_category == "localized_artifact"


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


def test_run_calls_sdk_with_lenient_shot_distance_and_prop_orientation_guidance(monkeypatch, tmp_path):
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
    text = kwargs["input"][0]["text"]
    assert "approximate, not exact" in text
    assert "Shot distance" in text
    assert "Prop/weapon orientation" in text


def test_run_calls_sdk_with_lenient_section_kept_separate_from_hard_requirements(monkeypatch, tmp_path):
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
    text = kwargs["input"][0]["text"]
    assert "hard requirements" in text
    assert "approximate, not exact" in text
    assert text.index("Perspective consistency") < text.index("approximate, not exact")
    assert text.index("approximate, not exact") < text.index("defect_category")


