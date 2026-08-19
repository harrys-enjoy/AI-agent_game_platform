"""Manual smoke test: render ONE already-generated keyframe through Veo directly.

Not a pytest test — it makes a real, billed Veo API call, so it is not part
of `pytest -v` and should be run by hand:

    python scripts/veo_single_shot_render_test.py \\
        --image media/gemini_pipeline_smoke_test/cand_a3fa9431.jpg \\
        --motion-prompt "Subtle, slow camera drift with slight micro-shake ..." \\
        --tier veo-3.1-lite

Purpose: isolate one variable. `beat_backend_map()` always routes setup/
conflict-beat scenes to the cheaper LTX backend and only climax/resolution
to Veo, so every real run so far has confounded "which model rendered this"
with "how important the scene was." This script re-renders an existing
LTX-routed scene's accepted keyframe through Veo instead, with the exact
same image and motion prompt, so a side-by-side comparison actually isolates
the backend as the variable instead of guessing from mixed evidence.

Takes the motion prompt either inline (--motion-prompt) or from a file
(--motion-prompt-file, one prompt, no surrounding quotes needed — simpler on
Windows than escaping a long quoted string on the command line).

Cost: Veo bills per second, quantized up to the nearest 4/6/8s clip.
veo-3.1-lite is $0.05/sec -> ~$0.20-0.40 for one clip depending on
--duration. veo-3.1-standard is 8x that. See PRICE_PER_SEC_USD in
render_backends/veo_backend.py for current rates.

Uses the same key resolution as the rest of the pipeline: VEO_API_KEY env
var, falling back to ~/.veo_api_key (plain text, just the key).
"""

import argparse
import sys
from pathlib import Path

from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.render_backends.veo_backend import VeoBackend, VeoBackendError
from video_draft_pipeline.schema import Candidate

OUTPUT_DIR = "media/gemini_pipeline_smoke_test"

VEO_TIERS = ("veo-3.1-lite", "veo-3.1-fast", "veo-3.1-standard")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--image", required=True, help="path to an existing keyframe .jpg/.png")
    parser.add_argument("--motion-prompt", default=None, help="the video_motion_prompt text, inline")
    parser.add_argument(
        "--motion-prompt-file", default=None, help="path to a text file containing the motion prompt"
    )
    parser.add_argument("--duration", type=float, default=6.0, dest="duration_sec")
    parser.add_argument("--tier", default="veo-3.1-lite", choices=VEO_TIERS)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument(
        "--candidate-id",
        default=None,
        help="defaults to the image's filename stem (e.g. cand_a3fa9431)",
    )
    args = parser.parse_args()
    if not args.motion_prompt and not args.motion_prompt_file:
        parser.error("pass either --motion-prompt or --motion-prompt-file")
    return args


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    motion_prompt = args.motion_prompt
    if not motion_prompt:
        motion_prompt = Path(args.motion_prompt_file).read_text(encoding="utf-8").strip()

    candidate_id = args.candidate_id or image_path.stem

    try:
        backend = VeoBackend(tier=args.tier, output_dir=args.output_dir)
    except MissingAPIKeyError as exc:
        raise SystemExit(str(exc))

    estimated_cost = backend.estimate_cost(args.duration_sec)
    print(f"Rendering {image_path} through Veo ({args.tier}, ~${estimated_cost:.2f})...")
    print(f"motion_prompt: {motion_prompt}")

    candidate = Candidate(candidate_id=candidate_id, image_url=str(image_path), generated_by="manual-test")

    try:
        result = backend.render(candidate=candidate, motion_prompt=motion_prompt, duration_sec=args.duration_sec)
    except VeoBackendError as exc:
        raise SystemExit(f"Render failed: {exc}")

    print(f"\nstatus: {result.status}")
    print(f"backend: {result.backend}")
    print(f"cost: ${result.cost_usd:.2f}")
    print(f"clip: {result.clip_url}")
    print("\nOK — compare this clip against the original LTX render for the same keyframe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
