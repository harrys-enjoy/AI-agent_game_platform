from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.render_backends.veo_backend import (
    VeoBackend,
    VeoBackendError,
    _round_to_allowed_duration,
)
from video_draft_pipeline.schema import Candidate


class _FakeVideo:
    def __init__(self, data: bytes):
        self._data = data

    def save(self, path):
        Path(path).write_bytes(self._data)


class _FakeGeneratedVideo:
    def __init__(self, video: _FakeVideo):
        self.video = video


class _FakeResponse:
    def __init__(self, generated_videos: list):
        self.generated_videos = generated_videos


class _FakeOperation:
    def __init__(self, done: bool, response=None):
        self.done = done
        self.response = response


def _candidate(image_path) -> Candidate:
    return Candidate(candidate_id="c1", image_url=str(image_path), generated_by="openai/gpt-image-2")


def _done_operation(video_bytes: bytes = b"fake-video-bytes") -> _FakeOperation:
    return _FakeOperation(
        done=True,
        response=_FakeResponse([_FakeGeneratedVideo(_FakeVideo(video_bytes))]),
    )


# --- Constructor ---


def test_veo_backend_rejects_unknown_tier():
    with pytest.raises(ValueError):
        VeoBackend(tier="veo-9000")


def test_veo_backend_rejects_unknown_resolution(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    with pytest.raises(ValueError):
        VeoBackend(tier="veo-3.1-fast", resolution="480p", client=MagicMock())


def test_veo_backend_rejects_4k_on_lite_tier(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    with pytest.raises(ValueError):
        VeoBackend(tier="veo-3.1-lite", resolution="4k", client=MagicMock())


def test_veo_backend_defaults_to_720p(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier="veo-3.1-fast", client=MagicMock())

    assert backend.resolution == "720p"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("VEO_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        VeoBackend(tier="veo-3.1-fast")


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier="veo-3.1-fast", api_key="explicit-key", client=MagicMock())

    assert backend.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier="veo-3.1-fast", client=MagicMock())

    assert backend.api_key == "env-key"


@pytest.mark.parametrize(
    "tier,expected_model_id,expected_price",
    [
        ("veo-3.1-lite", "veo-3.1-lite-generate-preview", 0.05),
        ("veo-3.1-fast", "veo-3.1-fast-generate-preview", 0.10),
        ("veo-3.1-standard", "veo-3.1-generate-preview", 0.40),
    ],
)
def test_tier_maps_to_model_id_and_price(monkeypatch, tier, expected_model_id, expected_price):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier=tier, client=MagicMock())

    assert backend.model_id == expected_model_id
    assert backend.price_per_sec_usd == expected_price


def test_output_dir_created_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    nested = tmp_path / "nested" / "media"
    assert not nested.exists()

    VeoBackend(tier="veo-3.1-fast", client=MagicMock(), output_dir=nested)

    assert nested.is_dir()


# --- Duration rounding ---


@pytest.mark.parametrize(
    "duration_sec,expected",
    [
        (0.0, 4),
        (3.9, 4),
        (4.0, 4),
        (4.9, 4),
        (5.0, 6),
        (5.1, 6),
        (6.0, 6),
        (6.9, 6),
        (7.0, 8),
        (7.1, 8),
        (8.0, 8),
        (100.0, 8),
    ],
)
def test_round_to_allowed_duration(duration_sec, expected):
    assert _round_to_allowed_duration(duration_sec) == expected


# --- render() ---


def test_render_calls_sdk_with_expected_model_image_and_config(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    _, kwargs = client.models.generate_videos.call_args
    assert kwargs["model"] == "veo-3.1-fast-generate-preview"
    assert kwargs["prompt"] == "pan left"
    assert kwargs["config"].aspect_ratio == "16:9"
    assert kwargs["config"].duration_seconds == 6
    assert kwargs["config"].resolution == "720p"
    assert kwargs["config"].generate_audio is None
    assert kwargs["image"].image_bytes == b"fake-image-bytes"
    assert kwargs["image"].mime_type == "image/png"
    assert result.backend == "veo-3.1-fast"
    assert result.status == "done"
    assert result.clip_url == str(tmp_path / "media" / "c1.mp4")
    assert Path(result.clip_url).read_bytes() == b"fake-video-bytes"
    assert result.cost_usd == 0.60


def test_render_sends_explicit_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast",
        resolution="1080p",
        client=client,
        output_dir=tmp_path / "media",
        poll_interval_sec=0,
    )

    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    _, kwargs = client.models.generate_videos.call_args
    assert kwargs["config"].resolution == "1080p"


def test_render_lite_tier_cost_math(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-lite", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    assert result.cost_usd == 0.30


def test_render_sends_mime_type_matching_source_image_extension(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.jpg"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    _, kwargs = client.models.generate_videos.call_args
    assert kwargs["image"].mime_type == "image/jpeg"


def test_render_polls_until_operation_done(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.side_effect = [_FakeOperation(done=False), _done_operation()]

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    assert client.operations.get.call_count == 2


def test_render_rounds_duration_before_calling_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=7.3)

    _, kwargs = client.models.generate_videos.call_args
    assert kwargs["config"].duration_seconds == 8


def test_render_wraps_sdk_exception_from_generate_videos(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.side_effect = RuntimeError("boom")

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    with pytest.raises(VeoBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


def test_render_raises_on_empty_generated_videos(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _FakeOperation(done=True, response=_FakeResponse([]))

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    with pytest.raises(VeoBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


def test_render_wraps_unreadable_image_path(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    missing_path = tmp_path / "does-not-exist.png"
    candidate = Candidate(candidate_id="c1", image_url=str(missing_path), generated_by="openai/gpt-image-2")

    backend = VeoBackend(
        tier="veo-3.1-fast", client=MagicMock(), output_dir=tmp_path / "media", poll_interval_sec=0
    )

    with pytest.raises(VeoBackendError):
        backend.render(candidate, motion_prompt="pan left", duration_sec=6.0)


def test_render_wraps_download_or_save_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()
    client.files.download.side_effect = RuntimeError("boom")

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    with pytest.raises(VeoBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


# --- estimate_cost() ---


@pytest.mark.parametrize(
    "tier,duration_sec,expected",
    [
        ("veo-3.1-lite", 6.0, 0.30),
        ("veo-3.1-fast", 6.0, 0.60),
        ("veo-3.1-standard", 6.0, 2.40),
    ],
)
def test_estimate_cost_per_tier(monkeypatch, tier, duration_sec, expected):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier=tier, client=MagicMock())

    assert backend.estimate_cost(duration_sec) == expected


def test_estimate_cost_matches_render_reported_cost(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    estimated = backend.estimate_cost(7.3)
    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=7.3)

    assert result.cost_usd == estimated


# --- Usage tracking ---


def test_render_records_usage_on_successful_call(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()
    usage_repository = MagicMock()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0,
        usage_repository=usage_repository,
    )
    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    usage_repository.record_call.assert_called_once()


def test_render_does_not_record_usage_when_generate_videos_call_rejected(monkeypatch, tmp_path):
    """A 429 (or any other) rejection from generate_videos() itself means
    Google never accepted the request - must not count as quota used."""

    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")
    usage_repository = MagicMock()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0,
        usage_repository=usage_repository,
    )

    with pytest.raises(VeoBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    usage_repository.record_call.assert_not_called()


def test_render_works_without_usage_repository(monkeypatch, tmp_path):
    """usage_repository defaults to None (e.g. every other test in this file) -
    render() must not crash trying to call .record_call() on None."""

    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0)

    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)
