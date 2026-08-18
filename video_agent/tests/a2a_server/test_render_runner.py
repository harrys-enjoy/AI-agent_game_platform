from video_draft_pipeline.a2a_server.render_runner import build_unresolved_scenes, run_render_task
from video_draft_pipeline.a2a_server.tasks import TaskStore
from video_draft_pipeline.orchestrator import PipelineError
from video_draft_pipeline.render_backends.veo_backend import VeoBackendError
from video_draft_pipeline.schema import Candidate, ConsistencyReview, Project, ProjectInput, Prompts, Scene, Storyboard


def _project_input() -> ProjectInput:
    return ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="할로윈 이벤트")


def test_run_render_task_marks_completed_with_media_url_on_success():
    store = TaskStore()
    record = store.create()

    def fake_render(project_input: ProjectInput) -> Project:
        return Project(
            project_id="proj_abc123",
            input=project_input,
            output_video_url="media/proj_abc123.mp4",
        )

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_COMPLETED"
    assert "http://localhost:8002/media/proj_abc123.mp4" in updated.answer
    assert updated.output_video_url == "http://localhost:8002/media/proj_abc123.mp4"


def test_run_render_task_marks_failed_on_pipeline_error():
    store = TaskStore()
    record = store.create()

    def failing_render(project_input: ProjectInput) -> Project:
        raise PipelineError("Scene scene_01 was rejected after 3 retries")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=failing_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_FAILED"
    assert "Scene scene_01 was rejected after 3 retries" in updated.answer


def test_run_render_task_marks_failed_with_real_reason_on_veo_backend_error():
    store = TaskStore()
    record = store.create()

    def failing_render(project_input: ProjectInput) -> Project:
        raise VeoBackendError("Veo call returned no generated videos")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=failing_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_FAILED"
    assert "Veo call returned no generated videos" in updated.answer
    assert "VeoBackendError" in updated.detail
    assert "Veo call returned no generated videos" in updated.detail


def test_run_render_task_marks_failed_on_unexpected_exception():
    store = TaskStore()
    record = store.create()

    def crashing_render(project_input: ProjectInput) -> Project:
        raise RuntimeError("boom")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=crashing_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_FAILED"
    assert updated.answer == "영상 생성 중 알 수 없는 오류가 발생했습니다."
    assert "RuntimeError" in updated.detail
    assert "boom" in updated.detail


def test_run_render_task_sets_project_id_on_success():
    store = TaskStore()
    record = store.create()

    def fake_render(project_input: ProjectInput) -> Project:
        return Project(project_id="proj_abc123", input=project_input, output_video_url="media/proj_abc123.mp4")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    assert store.get(record.task_id).project_id == "proj_abc123"


def test_run_render_task_marks_input_required_with_unresolved_scenes_message():
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
    assert updated.state == "TASK_STATE_INPUT_REQUIRED"
    assert updated.project_id == "proj_partial"
    assert "scene_04" in updated.answer
    assert "http://localhost:8002/media/a2a_server/cand_1.png" in updated.answer
    assert f"/tasks/{record.task_id}/scenes/" in updated.answer
    assert updated.unresolved_scenes == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": [],
            "referenceImageUrl": None,
        }
    ]


def test_run_render_task_does_not_overwrite_state_when_already_canceled():
    store = TaskStore()
    record = store.create()

    def fake_render(project_input: ProjectInput) -> Project:
        store.request_cancel(record.task_id)
        return Project(project_id="proj_abc123", input=project_input, output_video_url="media/p.mp4")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=fake_render)

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_CANCELED"


def test_run_render_task_does_not_mark_failed_when_canceled_during_pipeline_error():
    store = TaskStore()
    record = store.create()

    def failing_render(project_input: ProjectInput) -> Project:
        store.request_cancel(record.task_id)
        raise PipelineError("stopped")

    run_render_task(store, record.task_id, _project_input(), "http://localhost:8002", render_fn=failing_render)

    assert store.get(record.task_id).state == "TASK_STATE_CANCELED"


def test_build_unresolved_scenes_returns_only_unresolved_with_issues():
    storyboard = Storyboard(camera="c", subject="s", action="a", setting="set")
    resolved_review = ConsistencyReview(reviewed_by="r", passed=True, issues=[])
    unresolved_review = ConsistencyReview(reviewed_by="r", passed=False, issues=["shot too wide", "prop diagonal"])
    ok_scene = Scene(
        scene_id="scene_ok", beat_id="setup", order=1, duration_sec=5,
        storyboard=storyboard,
        accepted_candidate_id="cand_ok",
        candidates=[
            Candidate(
                candidate_id="cand_ok", image_url="media/cand_ok.png", generated_by="m",
                consistency_review=resolved_review,
            )
        ],
    )
    bad_scene = Scene(
        scene_id="scene_04", beat_id="resolution", order=4, duration_sec=5,
        storyboard=storyboard,
        needs_manual_fix=True,
        candidates=[
            Candidate(
                candidate_id="cand_1", image_url="media/a2a_server/cand_1.png", generated_by="m",
                consistency_review=unresolved_review,
            )
        ],
    )
    project = Project(project_id="proj_partial", input=_project_input())
    project.scenes = [ok_scene, bad_scene]

    result = build_unresolved_scenes(project, "http://localhost:8002")

    assert result == [
        {
            "sceneId": "scene_04",
            "imageUrl": "http://localhost:8002/media/a2a_server/cand_1.png",
            "issues": ["shot too wide", "prop diagonal"],
            "referenceImageUrl": "http://localhost:8002/media/cand_ok.png",
        }
    ]
