"""Manual smoke test: run the real all-Gemini pipeline end-to-end.

Not a pytest test — it makes real, billed API calls, so it is not part of
`pytest -v` and should be run by hand:

    python scripts/gemini_pipeline_smoke_test.py --brief "your own query here"

Exercises all seven real agent stages (planning/storyboard/prompt/image/
image_edit/review/director) via build_real_agents(). By default the render
backend stays on StubRenderBackend (no Veo/LTX billing) — pass
--render-backend to also render real video clips through Veo or LTX and,
with --assemble, concatenate them into one final .mp4 via ffmpeg.

--render-backend beat-split routes scenes by narrative importance instead of
using one backend for the whole video: climax/resolution scenes (the ones
that matter most) render through Veo (veo-3.1-lite), setup/conflict scenes
render through the cheaper LTX (ltx-2-3-fast) — see
agents.video_render_agent.beat_backend_map(). Requires both VEO_API_KEY and
LTX_API_KEY to be resolvable.

All keys go through config.load_api_keys(): the GEMINI_API_KEY/VEO_API_KEY/
LTX_API_KEY env vars, falling back to ~/.gemini_api_key, ~/.veo_api_key,
~/.ltx_api_key (plain text, just the key, created by hand outside any
terminal or chat so the value never appears in a command line or transcript).

Each run gets its own subfolder under media/gemini_pipeline_smoke_test/ (named
by timestamp, e.g. run_20260810_143012, or pass --run-id to name it yourself)
so images and clips from different tries don't pile up in one flat directory.

Every real Gemini call (planning/storyboard/prompt/image/image_edit/review/
director) is logged as one JSON line to that run's agent_log.jsonl by
default: timestamp, agent, model, sanitized input (image bytes replaced with
a length placeholder), and output. This is local file I/O only — it costs no
extra API tokens. Pass --no-log to disable, or --log-path to redirect it.
Use it to see exactly what each stage fed the next one (e.g. what
prompt_agent generated vs. what image_agent received).

Rough cost for the default 4-scene, no-retry project:
  Gemini stages: planning $0.01 + storyboard $0.01 +
    4 * (prompt $0.005 + image $0.039 + review $0.02 + director $0.03) = ~$0.40
  --render-backend stub (default): no additional real cost, but the pipeline's
    budget guard still counts StubRenderBackend's simulated cost (~$1.00 at
    veo-3.1-fast/10s default) toward --max-budget.
  --render-backend veo-3.1-lite / ltx-2-3-fast: real cost, roughly $0.05-0.06
    per rendered second, and Veo quantizes each scene up to a 4/6/8s clip
    (so 4 scenes = 16s minimum, ~$0.80 at the lite tier).
  --render-backend beat-split: 2 scenes (climax/resolution) at Veo lite
    (quantized to 4/6/8s each, ~$0.40 total) + 2 scenes (setup/conflict) at
    LTX fast (~$0.06/sec x actual scene length) — typically ~$0.55-0.70.
--max-budget defaults to $5.00 (matches ProjectInput's own default) to leave
room for the above plus a few director retries.
"""

import argparse
import sys
from datetime import datetime

from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.agents.video_render_agent import beat_backend_map
from video_draft_pipeline.orchestrator import PipelineError, run_pipeline
from video_draft_pipeline.render_backends.ltx_backend import LTXBackend
from video_draft_pipeline.render_backends.veo_backend import VeoBackend
from video_draft_pipeline.schema import ProjectInput

BASE_OUTPUT_DIR = "media/gemini_pipeline_smoke_test"

VEO_TIERS = ("veo-3.1-lite", "veo-3.1-fast", "veo-3.1-standard")
LTX_MODELS = ("ltx-2-3-fast", "ltx-2-3-pro")
BEAT_SPLIT = "beat-split"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--preset", default="이벤트", choices=["공개", "이벤트", "커뮤니티"])
    parser.add_argument("--scene-type", default="인게임", choices=["인게임", "스튜디오"], dest="scene_type")
    parser.add_argument("--duration", type=int, default=10, dest="duration_sec")
    parser.add_argument("--brief", default="할로윈 신규 캐릭터 공개 이벤트")
    parser.add_argument("--max-budget", type=float, default=5.00, dest="max_budget_usd")
    parser.add_argument(
        "--render-backend",
        default="stub",
        choices=["stub", BEAT_SPLIT, *VEO_TIERS, *LTX_MODELS],
        help=(
            "stub (default, free), a single real Veo/LTX tier, or beat-split "
            "(Veo for climax/resolution, LTX for setup/conflict) — all real "
            "options cost real money"
        ),
    )
    parser.add_argument(
        "--assemble", action="store_true", help="concatenate rendered clips into one .mp4 via ffmpeg"
    )
    parser.add_argument("--assembly-output", default=None, dest="assembly_output_path")
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "name for this run's output subfolder under "
            f"{BASE_OUTPUT_DIR}/ (default: a run_<timestamp> name)"
        ),
    )
    parser.add_argument(
        "--log-path",
        default=None,
        help="where to append per-call agent input/output as JSON lines (default: <run dir>/agent_log.jsonl)",
    )
    parser.add_argument("--no-log", action="store_true", help="disable agent input/output logging")
    args = parser.parse_args()
    if args.assemble and args.render_backend == "stub":
        parser.error("--assemble requires a real --render-backend (stub clips aren't real files)")
    return args


def _build_render_backend(name: str, output_dir: str):
    """Returns (render_backend, render_backend_by_beat) — exactly one is non-None
    for any real choice; both are None for "stub"."""
    if name == "stub":
        return None, None
    try:
        if name == BEAT_SPLIT:
            paid_backend = VeoBackend(tier="veo-3.1-lite", output_dir=output_dir)
            free_backend = LTXBackend(model="ltx-2-3-fast", output_dir=output_dir)
            return None, beat_backend_map(paid_backend, free_backend)
        if name in VEO_TIERS:
            return VeoBackend(tier=name, output_dir=output_dir), None
        return LTXBackend(model=name, output_dir=output_dir), None
    except MissingAPIKeyError as exc:
        raise SystemExit(str(exc))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    run_id = args.run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_output_dir = f"{BASE_OUTPUT_DIR}/{run_id}"

    project_input = ProjectInput(
        preset=args.preset,
        scene_type=args.scene_type,
        duration_sec=args.duration_sec,
        brief=args.brief,
        max_budget_usd=args.max_budget_usd,
    )

    log_path = None if args.no_log else (args.log_path or f"{run_output_dir}/agent_log.jsonl")
    try:
        agents = build_real_agents(output_dir=run_output_dir, log_path=log_path)
    except MissingAPIKeyError as exc:
        raise SystemExit(str(exc))

    render_backend, render_backend_by_beat = _build_render_backend(args.render_backend, run_output_dir)

    assembly_output_path = args.assembly_output_path
    if args.assemble and assembly_output_path is None:
        assembly_output_path = f"{run_output_dir}/final.mp4"

    print(
        f"Running all-Gemini pipeline (render_backend={args.render_backend}, "
        f"assemble={args.assemble}, max budget ${args.max_budget_usd:.2f})..."
    )
    print(f"run output dir: {run_output_dir}")
    try:
        project = run_pipeline(
            project_input,
            render_backend=render_backend,
            render_backend_by_beat=render_backend_by_beat,
            assemble=args.assemble,
            assembly_output_path=assembly_output_path,
            **agents,
        )
    except PipelineError as exc:
        raise SystemExit(f"Pipeline failed: {exc}")

    print(f"\nproject_id: {project.project_id}")
    print(f"beats: {[b.beat_id for b in project.narrative.beats]}")
    for scene in project.scenes:
        accepted = next(
            (c for c in scene.candidates if c.candidate_id == scene.accepted_candidate_id), None
        )
        print(
            f"\nscene {scene.scene_id} ({scene.beat_id}, {scene.duration_sec:.1f}s, "
            f"{scene.retry_count} retries):"
        )
        print(f"  image_prompt: {scene.prompts.image_prompt[:80]}...")
        print(f"  accepted image: {accepted.image_url if accepted else None}")
        print(f"  director: {accepted.director_decision.decision if accepted else None}")
        if scene.render:
            print(f"  render: {scene.render.status} ({scene.render.backend}, ${scene.render.cost_usd:.2f})")
            print(f"  clip: {scene.render.clip_url}")
        else:
            print(f"  render: SKIPPED — needs manual fix (resume with project_id={project.project_id!r}, scene_id={scene.scene_id!r})")

    if project.output_video_url:
        print(f"\nfinal video: {project.output_video_url}")

    if log_path:
        print(f"\nagent input/output log: {log_path}")
    print("\nOK — pipeline ran for real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
