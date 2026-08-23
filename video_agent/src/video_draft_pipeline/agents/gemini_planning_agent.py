from ..schema import Narrative, ProjectInput
from .gemini_agent_base import BaseGeminiAgent


def _build_input(project_input: ProjectInput) -> str:
    requirements = ", ".join(project_input.brand_requirements) or "none"
    return (
        "You are a creative director generating a 4-beat narrative for a game "
        "marketing video draft. Produce exactly one beat for each of: "
        "setup, conflict, climax, resolution.\n\n"
        "Also produce a style_guide that will be reused identically across "
        "every single scene in this video, so the video looks like one "
        "consistent production instead of 4 unrelated images:\n"
        "- visual_style: the rendering medium and art direction shared by every "
        "shot (e.g. '3D cinematic game render, Unreal Engine 5, dark fantasy').\n"
        "- color_palette: the 2-3 dominant colors and lighting mood shared by "
        "every shot. Describe only abstract color and light qualities (hues, "
        "tones, brightness, time of day) — never name a physical object, prop, "
        "or effect (e.g. smoke, fire, sparks), even as a color accent. An "
        "effect like that belongs only in the specific scene where it actually "
        "occurs, not in a palette every scene in the video inherits.\n"
        "- subject_blueprint: one detailed, self-contained description of the "
        "main character or subject's appearance (clothing, materials, colors, "
        "distinguishing features) — this exact description will be repeated "
        "verbatim in every scene, so it must fully describe the subject without "
        "relying on anything else in this narrative for context.\n"
        "- secondary_subject_blueprint: only if this video has a second "
        "recurring visual subject besides the main character (e.g. a creature, "
        "monster, vehicle, or antagonist that appears across multiple scenes), "
        "one detailed, self-contained description of its appearance (shape, "
        "materials, colors, distinguishing features) — this exact description "
        "will be repeated verbatim in every scene where it appears, the same "
        "way subject_blueprint is. If this video has no such second recurring "
        "subject, leave it empty.\n\n"
        f"Preset: {project_input.preset}\n"
        f"Scene type: {project_input.scene_type}\n"
        f"Brief: {project_input.brief}\n"
        f"Brand requirements: {requirements}"
    )


class PlanningAgentError(Exception):
    pass


class GeminiPlanningAgent(BaseGeminiAgent):
    error_cls = PlanningAgentError
    ESTIMATED_COST_USD = 0.01

    def __init__(
        self,
        model_name: str = "gemini-3.1-pro-preview",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
        log_path=None,
    ):
        super().__init__(model_name, api_key, client, base_url, log_path)

    def run(self, project_input: ProjectInput) -> Narrative:
        input_content = [{"type": "text", "text": _build_input(project_input)}]
        return self._structured_interaction(input_content, Narrative)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
