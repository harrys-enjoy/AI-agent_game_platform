import pytest

from video_draft_pipeline.project_store import ProjectStore, ProjectStoreError
from video_draft_pipeline.schema import Project, ProjectInput


def _project() -> Project:
    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event")
    return Project(project_id="proj_store_test", input=project_input, running_cost_usd=1.23)


def test_save_then_load_round_trips_project(tmp_path):
    store = ProjectStore(tmp_path)
    project = _project()

    store.save(project)
    loaded = store.load("proj_store_test")

    assert loaded.project_id == "proj_store_test"
    assert loaded.running_cost_usd == 1.23
    assert loaded.input.brief == "Halloween Event"


def test_load_raises_when_project_id_unknown(tmp_path):
    store = ProjectStore(tmp_path)

    with pytest.raises(ProjectStoreError):
        store.load("does-not-exist")


def test_load_raises_when_file_is_corrupt(tmp_path):
    store = ProjectStore(tmp_path)
    (tmp_path / "corrupt.json").write_text("not valid json{{{", encoding="utf-8")

    with pytest.raises(ProjectStoreError):
        store.load("corrupt")


def test_save_creates_root_dir_if_missing(tmp_path):
    root_dir = tmp_path / "nested" / "projects"
    store = ProjectStore(root_dir)

    store.save(_project())

    assert (root_dir / "proj_store_test.json").exists()
