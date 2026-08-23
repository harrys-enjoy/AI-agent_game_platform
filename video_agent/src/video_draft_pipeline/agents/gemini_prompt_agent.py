from ..schema import Prompts, Scene
from .gemini_agent_base import BaseGeminiAgent


_BEAT_INTENSITY = {
    "setup": "calm, wide, establishing",
    "conflict": "tense, uneasy",
    "climax": "intense, dynamic, high-contrast, high energy",
    "resolution": "triumphant, clear, confident",
}


def _build_input(scene: Scene, feedback: str | None = None) -> str:
    sb = scene.storyboard
    beat_intensity = _BEAT_INTENSITY.get(scene.beat_id, "")
    text = (
        "You are a prompt engineer generating an image generation prompt and a "
        "video motion prompt for a single scene of a game marketing video. The "
        "scene details below are in Korean, but you must write BOTH output "
        "prompts EXCLUSIVELY IN ENGLISH — image and video generation models "
        "render spatial detail and composition far more reliably from English "
        "prompts, even when the source project is Korean.\n\n"
        "image_prompt describes one static keyframe. Follow this structure: "
        "[Visual style/medium] + [Subject] + [Action/pose] + [Setting and "
        "lighting] + [Camera framing]. Do not include camera movement verbs "
        "(pan, zoom, dolly, track, push-in) — those belong only in "
        "video_motion_prompt, not here. Do not describe any on-image text, "
        "titles, logos, buttons, or item lists; image-gen models render "
        "non-Latin text unreliably, so any required text comes only from "
        "required_elements, appended separately after this prompt, not "
        "written by you here.\n\n"
        "video_motion_prompt describes only camera movement and physical "
        "motion. Follow this structure: [Camera movement type and speed] + "
        "[Subject/environment physical action] + [Pacing]. Do not repeat "
        "static visual details (colors, textures, framing) already covered "
        "by image_prompt.\n\n"
        "video_motion_prompt must not introduce any object, effect (smoke, "
        "fire, explosion, muzzle flash), or character that is not already "
        "present in image_prompt. The video model can only animate what "
        "exists in the source keyframe — describing a new effect purely in "
        "video_motion_prompt (e.g. 'a smoke grenade detonates' when no "
        "grenade was ever described in image_prompt) produces an effect "
        "with no physical object to anchor it to, so it renders disconnected "
        "from the scene. If a motion effect needs a source object, name that "
        "object in image_prompt first.\n\n"
        "When the Action below is a dynamic event (e.g. an explosion, a shot "
        "being fired, something breaking or opening), image_prompt must "
        "depict the pre-action state of that event, not the event already "
        "in progress — a pin still seated in a grenade, a trigger not yet "
        "pulled, a door not yet broken. Then video_motion_prompt can "
        "describe the transition away from that pre-action state (e.g. the "
        "pin coming free, the door beginning to break). Do not describe an "
        "outcome in video_motion_prompt (e.g. 'detonates', 'shatters') if "
        "its physical prerequisite state is absent from image_prompt.\n\n"
        "The Subject, Secondary subject, Visual style, and Color palette "
        "below are a fixed blueprint shared by every scene in this video — "
        "translate them faithfully into English and keep the description "
        "consistent with how the same character/style would be described in "
        "any other scene of this project. Do not invent a different look for "
        "it.\n\n"
        "If Secondary subject below is 'none', this video has no second "
        "recurring character or creature — do not introduce a second "
        "recurring character on your own. If the Action or Setting below "
        "still implies some other figure or creature is present, describe it "
        "generically and keep that description self-consistent within this "
        "scene, since no shared blueprint was provided for it.\n\n"
        "If the Camera framing below is a first-person or point-of-view shot "
        "(e.g. looking through a gun sight, scope, or the character's own "
        "eyes), the character is the viewer, not something visible on "
        "screen. In that case do NOT describe the Subject's face, helmet, or "
        "body as an externally visible figure — only describe what their own "
        "eyes would see: their hands, held weapon/equipment, and the "
        "environment. Reserve the full Subject description for shots where "
        "the character is actually visible on screen (third-person or "
        "over-the-shoulder framing).\n\n"
        "If that first-person shot is specifically looking through a scope "
        "or magnified optic, pick exactly ONE of these two compositions — "
        "never blend them: (1) pure scope-reticle HUD — the entire frame is "
        "the view through the optic glass, a circular vignette with a "
        "crosshair, and no gun body or hands visible at all; or (2) in-world "
        "aim-down-sights — the gun body and gripping hands are visible in "
        "frame with a small mounted scope lens, and there is no separate "
        "full-frame crosshair graphic overlaid on top. Combining a visible "
        "gun body with a full-frame crosshair overlay produces an "
        "incoherent double-scope image — do not describe both at once.\n\n"
        "Do not add any human figure, character, or silhouette to "
        "image_prompt beyond the Subject described below, unless the Action "
        "or Setting below explicitly calls for another person to be "
        "present. An incidental background figure that was not explicitly "
        "requested is especially prone to unstable, inconsistent rendering "
        "once the image is animated into video — omit it rather than invent "
        "it. If the scene is otherwise empty of people, say so explicitly "
        "(e.g. 'no other figures present').\n\n"
        "If the Camera framing below is a wide, establishing, or aerial/drone "
        "shot, keep the Subject in your output image_prompt to a brief, "
        "distant mention (e.g. 'a distant armored figure') instead of the "
        "full Subject blueprint detail. Loading a wide or establishing "
        "composition with detailed character description tends to pull the "
        "render toward a close-up medium shot instead of honoring the "
        "requested wide framing. Reserve the full Subject description for "
        "shots where the character is the primary focus.\n\n"
        f"Narrative beat: {scene.beat_id}"
        + (f" — match this intensity: {beat_intensity}" if beat_intensity else "")
        + "\n"
        f"Visual style: {sb.visual_style or 'unspecified'}\n"
        f"Color palette: {sb.color_palette or 'unspecified'}\n"
        f"Camera: {sb.camera}\n"
        f"Subject: {sb.subject}\n"
        f"Secondary subject: {sb.secondary_subject or 'none'}\n"
        f"Action: {sb.action}\n"
        f"Setting: {sb.setting}"
    )
    if feedback:
        text += (
            f"\n\nThe previous attempt was rejected with this feedback from the "
            f"director — revise the prompts to address it: {feedback}"
        )
    return text


class PromptAgentError(Exception):
    pass


class GeminiPromptAgent(BaseGeminiAgent):
    error_cls = PromptAgentError
    ESTIMATED_COST_USD = 0.005

    def __init__(
        self,
        model_name: str = "gemini-3.5-flash-lite",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
        log_path=None,
    ):
        super().__init__(model_name, api_key, client, base_url, log_path)

    def run(self, scene: Scene, feedback: str | None = None) -> Prompts:
        input_content = [{"type": "text", "text": _build_input(scene, feedback)}]
        parsed = self._structured_interaction(input_content, Prompts)
        image_prompt = parsed.image_prompt
        if scene.storyboard.required_elements:
            image_prompt = f"{image_prompt}, {', '.join(scene.storyboard.required_elements)}"
        return Prompts(image_prompt=image_prompt, video_motion_prompt=parsed.video_motion_prompt)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
