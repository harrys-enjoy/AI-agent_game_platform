import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.render_backends.ltx_backend import LTXBackend, LTXBackendError
from video_draft_pipeline.schema import Candidate


def _candidate(image_path) -> Candidate:
    return Candidate(candidate_id="c1", image_url=str(image_path), generated_by="openai/gpt-image-2")


def _fake_response(content: bytes, status_ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.content = content
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("422 error")
    return response


# --- Constructor ---


def test_rejects_unknown_model_resolution_combination():
    with pytest.raises(ValueError):
        LTXBackend(model="ltx-9000", resolution="1920x1080")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("LTX_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        LTXBackend()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("LTX_API_KEY", "env-key")

    backend = LTXBackend(api_key="explicit-key")

    assert backend.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("LTX_API_KEY", "env-key")

    backend = LTXBackend()

    assert backend.api_key == "env-key"


def test_default_model_and_resolution(monkeypatch):
    monkeypatch.setenv("LTX_API_KEY", "env-key")

    backend = LTXBackend()

    assert backend.model == "ltx-2-3-fast"
    assert backend.resolution == "1920x1080"
    assert backend.name == "ltx-2-3-fast"


def test_output_dir_created_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    nested = tmp_path / "nested" / "media"
    assert not nested.exists()

    LTXBackend(output_dir=nested)

    assert nested.is_dir()


# --- render() ---


def test_render_calls_api_with_expected_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    mock_post = MagicMock(return_value=_fake_response(b"fake-video-bytes"))
    monkeypatch.setattr("video_draft_pipeline.render_backends.ltx_backend.requests.post", mock_post)

    backend = LTXBackend(output_dir=tmp_path / "media")
    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.ltx.io/v1/image-to-video"
    assert kwargs["headers"]["Authorization"] == "Bearer env-key"
    payload = kwargs["json"]
    assert payload["model"] == "ltx-2-3-fast"
    assert payload["resolution"] == "1920x1080"
    assert payload["duration"] == 6
    assert payload["prompt"] == "pan left"
    assert payload["generate_audio"] is True
    expected_b64 = base64.b64encode(b"fake-image-bytes").decode("utf-8")
    assert payload["image_uri"] == f"data:image/png;base64,{expected_b64}"
    assert result.backend == "ltx-2-3-fast"
    assert result.status == "done"
    assert result.clip_url == str(tmp_path / "media" / "c1.mp4")
    assert Path(result.clip_url).read_bytes() == b"fake-video-bytes"
    assert result.cost_usd == 0.36


def test_render_sends_mime_type_matching_source_image_extension(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    image_path = tmp_path / "candidate.jpg"
    image_path.write_bytes(b"fake-image-bytes")
    mock_post = MagicMock(return_value=_fake_response(b"fake-video-bytes"))
    monkeypatch.setattr("video_draft_pipeline.render_backends.ltx_backend.requests.post", mock_post)

    backend = LTXBackend(output_dir=tmp_path / "media")
    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    _, kwargs = mock_post.call_args
    expected_b64 = base64.b64encode(b"fake-image-bytes").decode("utf-8")
    assert kwargs["json"]["image_uri"] == f"data:image/jpeg;base64,{expected_b64}"


def test_render_rounds_duration_before_calling_api(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    mock_post = MagicMock(return_value=_fake_response(b"fake-video-bytes"))
    monkeypatch.setattr("video_draft_pipeline.render_backends.ltx_backend.requests.post", mock_post)

    backend = LTXBackend(output_dir=tmp_path / "media")
    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=7.3)

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["duration"] == 7


def test_render_wraps_unreadable_image_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    missing_path = tmp_path / "does-not-exist.png"
    candidate = Candidate(candidate_id="c1", image_url=str(missing_path), generated_by="openai/gpt-image-2")

    backend = LTXBackend(output_dir=tmp_path / "media")

    with pytest.raises(LTXBackendError):
        backend.render(candidate, motion_prompt="pan left", duration_sec=6.0)


def test_render_wraps_non_200_response(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    mock_post = MagicMock(return_value=_fake_response(b"", status_ok=False))
    monkeypatch.setattr("video_draft_pipeline.render_backends.ltx_backend.requests.post", mock_post)

    backend = LTXBackend(output_dir=tmp_path / "media")

    with pytest.raises(LTXBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


def test_render_wraps_connection_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    mock_post = MagicMock(side_effect=requests.exceptions.ConnectionError("boom"))
    monkeypatch.setattr("video_draft_pipeline.render_backends.ltx_backend.requests.post", mock_post)

    backend = LTXBackend(output_dir=tmp_path / "media")

    with pytest.raises(LTXBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


# --- estimate_cost() ---


@pytest.mark.parametrize(
    "model,resolution,duration_sec,expected",
    [
        ("ltx-2-3-fast", "1920x1080", 6.0, 0.36),
        ("ltx-2-3-fast", "2560x1440", 6.0, 0.72),
        ("ltx-2-3-fast", "3840x2160", 6.0, 1.44),
        ("ltx-2-3-pro", "1920x1080", 6.0, 0.48),
        ("ltx-2-3-pro", "2560x1440", 6.0, 0.96),
        ("ltx-2-3-pro", "3840x2160", 6.0, 1.92),
    ],
)
def test_estimate_cost_per_model_resolution(monkeypatch, model, resolution, duration_sec, expected):
    monkeypatch.setenv("LTX_API_KEY", "env-key")

    backend = LTXBackend(model=model, resolution=resolution)

    assert backend.estimate_cost(duration_sec) == expected


def test_estimate_cost_matches_render_reported_cost(monkeypatch, tmp_path):
    monkeypatch.setenv("LTX_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")
    mock_post = MagicMock(return_value=_fake_response(b"fake-video-bytes"))
    monkeypatch.setattr("video_draft_pipeline.render_backends.ltx_backend.requests.post", mock_post)

    backend = LTXBackend(output_dir=tmp_path / "media")

    estimated = backend.estimate_cost(7.3)
    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=7.3)

    assert result.cost_usd == estimated
