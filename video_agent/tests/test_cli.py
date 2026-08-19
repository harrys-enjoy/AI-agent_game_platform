import json

import pytest

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
    assert args.project_store_dir == "media/projects"


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


def test_main_returns_1_on_invalid_input_without_traceback(capsys):
    exit_code = main(
        ["--preset", "이벤트", "--scene-type", "인게임", "--duration", "0", "--brief", "Bad"]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert len(captured.err.strip().splitlines()) == 1


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


def test_parse_args_rejects_non_positive_budget(capsys):
    with pytest.raises(SystemExit) as exc_info:
        parse_args(
            [
                "--preset", "이벤트",
                "--scene-type", "인게임",
                "--duration", "30",
                "--brief", "Halloween Event",
                "--max-budget", "-5",
            ]
        )

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "Traceback" not in captured.err
    assert "--max-budget" in captured.err


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


def _stored_project_with_single_unresolved_scene(tmp_path) -> str:
    # Exactly ONE needs_manual_fix scene: resuming it fully resolves the
    # project, which previously triggered resume_scene_with_image's
    # unconditional assembly attempt against fake stub:// clip URLs — a real
    # ffmpeg CalledProcessError. resume_main now passes assemble=False, so
    # this scenario must succeed without ever invoking ffmpeg.
    store = ProjectStore(tmp_path)
    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=5, brief="테스트")
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    scene = Scene(
        scene_id="scene_bad", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard, prompts=Prompts(image_prompt="p", video_motion_prompt="m"),
        needs_manual_fix=True,
        candidates=[Candidate(candidate_id="cand_bad_1", image_url="stub://bad.png", generated_by="m")],
    )
    project = Project(project_id="proj_cli_resume_single_scene_test", input=project_input)
    project.scenes = [scene]
    store.save(project)
    return project.project_id


def test_resume_main_resolves_last_unresolved_scene_without_assembling(capsys, tmp_path):
    project_id = _stored_project_with_single_unresolved_scene(tmp_path)

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
    assert payload["output_video_url"] is None


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
