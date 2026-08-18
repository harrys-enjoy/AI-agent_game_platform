"""Manual smoke test: run real VeoBackend and LTXBackend render() calls.

Not a pytest test — it makes real, billed network calls and needs real API
keys, so it is not part of `pytest -v` and should be run by hand:

    python scripts/render_backend_smoke_test.py path/to/a/real/image.png

Bypasses run_pipeline() and every agent stage entirely (planning/storyboard/
prompt/image/image_edit/review/director all route through Elice, which we
don't have keys for yet) — this only exercises the two real render backends
directly, using a real local image file you already have (it does not need
to be pipeline-generated).

Keys are read from VEO_API_KEY/LTX_API_KEY env vars if set, otherwise from
~/.veo_api_key / ~/.ltx_api_key (plain-text files containing just the key,
created by hand outside any terminal/chat so the value never appears in a
command line or tool transcript). Same pattern as scripts/nvidia_smoke_test.py.

Uses the cheapest tier for each backend (Veo lite, LTX fast @ 1080p) and a
short 4-second duration to keep real cost low: ~$0.20 (Veo) + ~$0.24 (LTX)
= ~$0.44 total for both calls.
"""

import os
import sys
from pathlib import Path

from video_draft_pipeline.render_backends.ltx_backend import LTXBackend
from video_draft_pipeline.render_backends.veo_backend import VeoBackend
from video_draft_pipeline.schema import Candidate

OUTPUT_DIR = "media/render_backend_smoke_test"
DURATION_SEC = 4.0
MOTION_PROMPT = "slow pan across the scene, gentle camera drift"

VEO_KEY_FILE_FALLBACK = Path.home() / ".veo_api_key"
LTX_KEY_FILE_FALLBACK = Path.home() / ".ltx_api_key"


def _load_key(env_var: str, file_fallback: Path) -> str:
    key = os.environ.get(env_var)
    if key:
        return key
    if file_fallback.exists():
        return file_fallback.read_text().strip()
    raise SystemExit(
        f"No {env_var} found. Set the {env_var} env var, or create "
        f"{file_fallback} containing just the key on one line."
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: python {sys.argv[0]} path/to/a/real/image.png")
    image_path = Path(sys.argv[1])
    if not image_path.is_file():
        raise SystemExit(f"Not a file: {image_path}")

    candidate = Candidate(
        candidate_id="smoke_test_candidate",
        image_url=str(image_path),
        generated_by="manual-smoke-test",
    )

    veo_backend = VeoBackend(
        tier="veo-3.1-lite",
        api_key=_load_key("VEO_API_KEY", VEO_KEY_FILE_FALLBACK),
        output_dir=f"{OUTPUT_DIR}/veo",
    )
    print(f"Calling VeoBackend (estimated cost: ${veo_backend.estimate_cost(DURATION_SEC):.2f})...")
    veo_result = veo_backend.render(candidate, motion_prompt=MOTION_PROMPT, duration_sec=DURATION_SEC)
    print(veo_result.model_dump_json(indent=2))

    ltx_backend = LTXBackend(
        model="ltx-2-3-fast",
        resolution="1920x1080",
        api_key=_load_key("LTX_API_KEY", LTX_KEY_FILE_FALLBACK),
        output_dir=f"{OUTPUT_DIR}/ltx",
    )
    print(f"\nCalling LTXBackend (estimated cost: ${ltx_backend.estimate_cost(DURATION_SEC):.2f})...")
    ltx_result = ltx_backend.render(candidate, motion_prompt=MOTION_PROMPT, duration_sec=DURATION_SEC)
    print(ltx_result.model_dump_json(indent=2))

    total_cost = veo_result.cost_usd + ltx_result.cost_usd
    print(f"\nTotal real cost: ${total_cost:.2f}")


if __name__ == "__main__":
    main()
