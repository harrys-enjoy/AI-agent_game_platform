from pathlib import Path

from .schema import Project


class ProjectStoreError(Exception):
    pass


class ProjectStore:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, project_id: str) -> Path:
        return self.root_dir / f"{project_id}.json"

    def save(self, project: Project) -> None:
        self._path_for(project.project_id).write_text(
            project.model_dump_json(indent=2), encoding="utf-8"
        )

    def load(self, project_id: str) -> Project:
        path = self._path_for(project_id)
        if not path.exists():
            raise ProjectStoreError(f"No stored project found for project_id={project_id!r}")
        try:
            return Project.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ProjectStoreError(
                f"Stored project file for project_id={project_id!r} is corrupt: {exc}"
            ) from exc

    def delete(self, project_id: str) -> None:
        """No-op if the project file doesn't exist - deleting a task whose
        project was never saved (e.g. failed before rendering) is fine."""

        self._path_for(project_id).unlink(missing_ok=True)
