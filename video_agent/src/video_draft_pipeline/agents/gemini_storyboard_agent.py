from pydantic import BaseModel, ValidationError

from ..schema import BeatId, Narrative, ProjectInput, Scene, Storyboard, StyleGuide
from .gemini_agent_base import BaseGeminiAgent


def _build_input(narrative: Narrative, project_input: ProjectInput) -> str:
    beats_description = "\n".join(
        f"- {beat.beat_id}: {beat.description} (tone: {beat.tone})" for beat in narrative.beats
    )
    sg = narrative.style_guide
    return (
        "You are a creative director generating a shot-by-shot storyboard for a "
        "game marketing video draft. For each beat provided, produce one scene: "
        "a camera direction, the subject, the action, the setting, any required "
        "on-screen elements, and a duration_weight expressing how much relative "
        "screen time this beat deserves compared to the others (for example, a "
        "climax beat might deserve more weight than a setup beat). Respond in "
        "Korean, matching the language of the input.\n\n"
        "This video has a fixed style guide — keep every scene's camera/action/"
        "setting choices consistent with it (e.g. a shot proposed for a "
        "low-poly art style shouldn't call for photorealistic lighting):\n"
        f"- Visual style: {sg.visual_style or 'unspecified'}\n"
        f"- Color palette: {sg.color_palette or 'unspecified'}\n"
        f"- Subject: {sg.subject_blueprint or 'unspecified'}\n\n"
        f"Preset: {project_input.preset}\n"
        f"Scene type: {project_input.scene_type}\n"
        f"Brief: {project_input.brief}\n"
        f"Beats:\n{beats_description}"
    )


def _drafts_to_scenes(
    drafts: list["SceneDraft"], project_input: ProjectInput, style_guide: StyleGuide | None = None
) -> list[Scene]:
    style_guide = style_guide or StyleGuide()
    total_weight = sum(draft.duration_weight for draft in drafts)
    n = len(drafts)
    scenes: list[Scene] = []
    running = 0.0
    for i, draft in enumerate(drafts):
        if i < n - 1:
            # Round as each duration is computed (not just at the end) so the
            # running total used for the last scene's remainder is already
            # rounded — otherwise rounding each value independently could make
            # the durations sum to slightly off the requested duration_sec.
            duration = round(project_input.duration_sec * draft.duration_weight / total_weight, 2)
            running += duration
        else:
            duration = round(project_input.duration_sec - running, 2)
        required_elements = (
            list(project_input.brand_requirements) if draft.beat_id == "resolution" else []
        )
        scenes.append(
            Scene(
                scene_id=f"scene_{i + 1:02d}",
                beat_id=draft.beat_id,
                order=i + 1,
                duration_sec=duration,
                storyboard=Storyboard(
                    camera=draft.camera,
                    # subject_blueprint is deterministically reused across every scene
                    # instead of trusting the LLM to reword the same character
                    # identically on each independent draft entry — see the
                    # "global style system" design in docs/superpowers.
                    subject=style_guide.subject_blueprint or draft.subject,
                    action=draft.action,
                    setting=draft.setting,
                    visual_style=style_guide.visual_style,
                    color_palette=style_guide.color_palette,
                    required_elements=required_elements,
                ),
            )
        )
    return scenes


class StoryboardAgentError(Exception):
    pass


class SceneDraft(BaseModel):
    beat_id: BeatId
    camera: str
    subject: str
    action: str
    setting: str
    required_elements: list[str]
    duration_weight: float


class StoryboardDraft(BaseModel):
    scenes: list[SceneDraft]


class GeminiStoryboardAgent(BaseGeminiAgent):
    error_cls = StoryboardAgentError
    ESTIMATED_COST_USD = 0.01

    def __init__(
        self,
        model_name: str = "gemini-3.6-flash",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
        log_path=None,
    ):
        super().__init__(model_name, api_key, client, base_url, log_path)

    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]:
        if not narrative.beats:
            raise StoryboardAgentError("Narrative has no beats; cannot build a storyboard.")
        input_content = [{"type": "text", "text": _build_input(narrative, project_input)}]
        draft = self._structured_interaction(input_content, StoryboardDraft)
        draft_beat_ids = [scene.beat_id for scene in draft.scenes]
        expected_beat_ids = [beat.beat_id for beat in narrative.beats]
        if draft_beat_ids != expected_beat_ids:
            raise StoryboardAgentError(
                f"Gemini storyboard response beats {draft_beat_ids} do not match "
                f"narrative beats {expected_beat_ids}"
            )
        if any(scene.duration_weight <= 0 for scene in draft.scenes):
            raise StoryboardAgentError(
                "Gemini storyboard response contained a non-positive duration_weight"
            )
        try:
            return _drafts_to_scenes(draft.scenes, project_input, narrative.style_guide)
        except ValidationError as exc:
            raise StoryboardAgentError(f"Gemini storyboard produced unusable durations: {exc}") from exc

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
