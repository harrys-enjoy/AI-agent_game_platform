"""Free, deterministic local stand-in for the video-agent A2A server.

Lets you test the Main Agent's "Needs Manual Fix" UI end-to-end (the chat
upload card, the My Tasks "Needs Manual Fix" badge and click-to-reopen, and
the resume/upload flow) without calling any paid Gemini or Veo API.

Any chat request to this server returns the same canned single-scene
project that needs a manual fix. Uploading a fix resolves it using a real
(but tiny, locally pre-generated) video clip, so the full resume -> ffmpeg
assemble -> "Done" path is exercised too, not just the failure state.

Requires ffmpeg on PATH (used once at startup to generate a placeholder
image and a placeholder clip; the same dependency the real pipeline needs
for assembly).

Run:
    VIDEO_SERVICE_TOKEN=dev-secret python scripts/fake_video_agent_server.py
        VIDEO_SERVICE_TOKEN is required -- this server builds its app via
        create_app(), so /a2a/* routes enforce Bearer auth just like the
        real server; without it, every chat request 401s.

    FAKE_SCENARIO=with_anchor VIDEO_SERVICE_TOKEN=dev-secret python scripts/fake_video_agent_server.py
        Shows a scene that already has an established reference image
        (a project-level consistency anchor) alongside the scene that
        needs a manual fix, instead of the default no-anchor scenario.

Then point the Main Agent at it (see AI-agent_game_platform's README/
docker-compose for the equivalent env vars) and send any video-generation
request through its chat.
"""

import os
import subprocess
import uuid
from pathlib import Path

import uvicorn

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.brief_intake import IntakeResult
from video_draft_pipeline.a2a_server.tasks import TaskStore
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent
from video_draft_pipeline.project_store import ProjectStore
from video_draft_pipeline.schema import (
    Candidate,
    ConsistencyReview,
    Project,
    ProjectInput,
    RenderResult,
    Scene,
    Storyboard,
)

# The A2A server mounts StaticFiles at /media pointed at media_dir, and its
# own assembly step hardcodes final videos to "media/{project_id}.mp4" with
# no override available through the resume endpoint -- so media_dir must be
# the top-level "media" directory, not a subfolder, or the assembled video's
# URL and its real file location diverge and playback 404s.
MEDIA_DIR = Path("media")
SUBDIR_NAME = "fake_video_agent_server"
FS_OUTPUT_DIR = MEDIA_DIR / SUBDIR_NAME

FAKE_SCENARIO = os.environ.get("FAKE_SCENARIO", "no_anchor")  # "no_anchor" | "with_anchor"


def _generate_placeholder_image(path: Path, color: str = "slateblue") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=512x512", "-frames:v", "1", "-update", "1", str(path)],
        check=True,
    )


def _generate_placeholder_clip(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=seagreen:s=512x512:d=2", "-c:v", "libx264", "-t", "2", str(path)],
        check=True,
    )


class FakeIntakeAgent:
    """Stands in for BriefIntakeAgent: no Gemini call, always accepts the
    request with fixed parameters so the fake render_fn always runs."""

    def run(self, text: str) -> IntakeResult:
        return IntakeResult(brief=text, preset="이벤트", scene_type="인게임", duration_sec=8, max_budget_usd=1.0)


class FixedClipBackend:
    """Stands in for VeoBackend/LTXBackend: no network call, returns a
    pre-generated real clip file so ffmpeg assembly has something valid to
    concatenate on resume."""

    def __init__(self, clip_path: Path):
        self.clip_path = clip_path

    def estimate_cost(self, duration_sec: float) -> float:
        return 0.0

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        return RenderResult(backend="veo-3.1-fast", status="done", clip_url=str(self.clip_path), cost_usd=0.0)


def build_fake_project(image_url_relative_to_media_dir: str) -> Project:
    project_id = f"proj_fake_{uuid.uuid4().hex[:8]}"
    scene = Scene(
        scene_id="scene_01",
        beat_id="setup",
        order=0,
        duration_sec=4.0,
        storyboard=Storyboard(
            camera="wide establishing shot",
            subject="cyberpunk operative",
            action="stands still under neon signage",
            setting="rain-slicked alley",
        ),
        candidates=[
            Candidate(
                candidate_id="cand_fake01",
                image_url=image_url_relative_to_media_dir,
                generated_by="fake_harness",
                consistency_review=ConsistencyReview(
                    reviewed_by="fake_harness",
                    passed=False,
                    issues=["헬멧 디자인이 이전 씬과 일치하지 않음 (테스트용 고정 사유)"],
                    defect_category="localized_artifact",
                ),
            )
        ],
        needs_manual_fix=True,
        retry_count=3,
        max_retries=3,
    )
    return Project(
        project_id=project_id,
        input=ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=4, brief="테스트용 고정 시나리오"),
        scenes=[scene],
    )


def build_fake_project_with_anchor(anchor_image_url_relative_to_media_dir: str, image_url_relative_to_media_dir: str, clip_path: Path) -> Project:
    project_id = f"proj_fake_{uuid.uuid4().hex[:8]}"
    anchor_scene = Scene(
        scene_id="scene_00",
        beat_id="setup",
        order=0,
        duration_sec=4.0,
        storyboard=Storyboard(
            camera="wide establishing shot",
            subject="cyberpunk operative",
            action="stands still under neon signage",
            setting="rain-slicked alley",
        ),
        accepted_candidate_id="cand_anchor01",
        candidates=[
            Candidate(
                candidate_id="cand_anchor01",
                image_url=anchor_image_url_relative_to_media_dir,
                generated_by="fake_harness",
                consistency_review=ConsistencyReview(
                    reviewed_by="fake_harness", passed=True, issues=[], defect_category="none",
                ),
            )
        ],
        render=RenderResult(backend="veo-3.1-fast", status="done", clip_url=str(clip_path), cost_usd=0.0),
    )
    failing_scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=4.0,
        storyboard=Storyboard(
            camera="tight close-up",
            subject="cyberpunk operative",
            action="tilts head up toward camera",
            setting="rain-slicked alley",
        ),
        candidates=[
            Candidate(
                candidate_id="cand_fake01",
                image_url=image_url_relative_to_media_dir,
                generated_by="fake_harness",
                consistency_review=ConsistencyReview(
                    reviewed_by="fake_harness",
                    passed=False,
                    issues=["헬멧 디자인이 이전 씬과 일치하지 않음 (테스트용 고정 사유)"],
                    defect_category="localized_artifact",
                ),
            )
        ],
        needs_manual_fix=True,
        retry_count=3,
        max_retries=3,
    )
    return Project(
        project_id=project_id,
        input=ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=8, brief="테스트용 고정 시나리오 (앵커 포함)"),
        scenes=[anchor_scene, failing_scene],
    )


def main() -> None:
    FS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_path = FS_OUTPUT_DIR / "placeholder_scene.png"
    clip_path = FS_OUTPUT_DIR / "placeholder_clip.mp4"
    # render_runner.py builds public URLs as f"{media_public_base_url}/{image_url}",
    # and the StaticFiles mount is "/media" pointed at MEDIA_DIR -- so this string
    # must itself start with "media/" (matching how real agents set image_url when
    # writing under OUTPUT_DIR = "media/a2a_server") or the URL skips the mount.
    image_url_relative_to_media_dir = f"{MEDIA_DIR.name}/{SUBDIR_NAME}/placeholder_scene.png"
    print(f"Generating placeholder image/clip via ffmpeg into {FS_OUTPUT_DIR} ...")
    _generate_placeholder_image(image_path)
    _generate_placeholder_clip(clip_path)

    anchor_image_path = FS_OUTPUT_DIR / "placeholder_anchor_scene.png"
    anchor_image_url_relative_to_media_dir = f"{MEDIA_DIR.name}/{SUBDIR_NAME}/placeholder_anchor_scene.png"
    if FAKE_SCENARIO == "with_anchor":
        _generate_placeholder_image(anchor_image_path, color="orange")

    project_store = ProjectStore(str(FS_OUTPUT_DIR / "projects"))

    def fake_render_fn(project_input: ProjectInput) -> Project:
        if FAKE_SCENARIO == "with_anchor":
            project = build_fake_project_with_anchor(anchor_image_url_relative_to_media_dir, image_url_relative_to_media_dir, clip_path)
        else:
            project = build_fake_project(image_url_relative_to_media_dir)
        project_store.save(project)
        return project

    def fake_resume_render_agent_fn() -> VideoRenderAgent:
        return VideoRenderAgent(backend=FixedClipBackend(clip_path))

    app = create_app(
        self_internal_url="http://localhost:8002",
        media_public_base_url="http://localhost:8002",
        media_dir=str(MEDIA_DIR),
        task_store=TaskStore(),
        intake_agent=FakeIntakeAgent(),
        render_fn=fake_render_fn,
        project_store=project_store,
        resume_render_agent_fn=fake_resume_render_agent_fn,
    )

    print("Fake video-agent server ready on http://localhost:8002 (zero API cost).")
    print(f"Scenario: {FAKE_SCENARIO} (set FAKE_SCENARIO=with_anchor or =no_anchor to switch).")
    uvicorn.run(app, host="0.0.0.0", port=8002)


if __name__ == "__main__":
    main()
