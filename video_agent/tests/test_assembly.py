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
    expected_a = Path("a.mp4").resolve().as_posix()
    expected_b = Path("b.mp4").resolve().as_posix()
    assert content == f"file '{expected_a}'\nfile '{expected_b}'\n"


def test_write_concat_list_resolves_paths_relative_to_the_list_itself(tmp_path):
    nested_clip = tmp_path / "nested" / "clip.mp4"
    concat_list_path = tmp_path / "list.txt"

    write_concat_list([str(nested_clip)], str(concat_list_path))

    content = concat_list_path.read_text(encoding="utf-8")
    assert content == f"file '{nested_clip.resolve().as_posix()}'\n"


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
    expected_a = Path("a.mp4").resolve().as_posix()
    expected_b = Path("b.mp4").resolve().as_posix()
    assert concat_list_path.read_text(encoding="utf-8") == f"file '{expected_a}'\nfile '{expected_b}'\n"


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
