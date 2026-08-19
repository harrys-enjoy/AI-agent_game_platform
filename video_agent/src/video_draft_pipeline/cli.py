import argparse
import json
import sys

from pydantic import ValidationError

from .agents.video_render_agent import VideoRenderAgent
from .config import ModelConfig
from .orchestrator import PipelineError, format_candidate_diagnostics, resume_scene_with_image, run_pipeline
from .project_store import ProjectStore, ProjectStoreError
from .render_backends.stub_backend import StubRenderBackend
from .schema import ProjectInput


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the video draft pipeline end-to-end (stub agents)."
    )
    parser.add_argument("--preset", required=True, choices=["공개", "이벤트", "커뮤니티"])
    parser.add_argument(
        "--scene-type", required=True, choices=["인게임", "스튜디오"], dest="scene_type"
    )
    parser.add_argument("--duration", required=True, type=int, dest="duration_sec")
    parser.add_argument("--brief", required=True)
    parser.add_argument("--max-budget", type=float, default=5.00, dest="max_budget_usd")
    parser.add_argument("--project-store-dir", default="media/projects", dest="project_store_dir")
    args = parser.parse_args(argv)
    if args.max_budget_usd <= 0:
        parser.error(f"--max-budget must be greater than 0 (got {args.max_budget_usd})")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        project_input = ProjectInput(
            preset=args.preset,
            scene_type=args.scene_type,
            duration_sec=args.duration_sec,
            brief=args.brief,
            max_budget_usd=args.max_budget_usd,
        )
        project_store = ProjectStore(args.project_store_dir)
        project = run_pipeline(project_input, project_store=project_store)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        print(f"error: invalid input: {errors}", file=sys.stderr)
        return 1
    except PipelineError as exc:
        print(f"error: pipeline failed: {exc}", file=sys.stderr)
        return 1

    unresolved = [scene for scene in project.scenes if scene.needs_manual_fix]
    if unresolved:
        lines = [
            "warning: the following scenes need a manual fix — resume with "
            "`python -m video_draft_pipeline.cli resume --project-store-dir "
            f"{args.project_store_dir} --project-id {project.project_id} --scene-id <id> --image <path>`:"
        ]
        for scene in unresolved:
            lines.append(f"  {scene.scene_id}: {scene.candidates[-1].image_url}")
            lines.append(format_candidate_diagnostics(scene.candidates))
        print("\n".join(lines), file=sys.stderr)

    print(json.dumps(project.model_dump(), ensure_ascii=False, indent=2))
    return 0


def parse_resume_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video_draft_pipeline.cli resume",
        description="Resume a scene that needs a manual fix by submitting a replacement image.",
    )
    parser.add_argument("--project-store-dir", required=True, dest="project_store_dir")
    parser.add_argument("--project-id", required=True, dest="project_id")
    parser.add_argument("--scene-id", required=True, dest="scene_id")
    parser.add_argument("--image", required=True, dest="image_path")
    return parser.parse_args(argv)


def resume_main(argv: list[str] | None = None) -> int:
    args = parse_resume_args(argv)
    store = ProjectStore(args.project_store_dir)
    try:
        project = store.load(args.project_id)
    except ProjectStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    render_agent = VideoRenderAgent(backend=StubRenderBackend(tier=ModelConfig().render_backend))
    try:
        project = resume_scene_with_image(
            project, args.scene_id, args.image_path, render_agent, project_store=store, assemble=False
        )
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(project.model_dump(), ensure_ascii=False, indent=2))
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["resume"]:
        return resume_main(argv[1:])
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli_main())
