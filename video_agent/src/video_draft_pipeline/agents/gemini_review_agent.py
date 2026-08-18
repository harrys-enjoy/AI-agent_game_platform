import base64
from pathlib import Path

from pydantic import BaseModel

from ..schema import Candidate, ConsistencyReview, DefectCategory, Prompts
from .gemini_agent_base import BaseGeminiAgent, mime_type_for_image_path


class ReviewAgentError(Exception):
    pass


class ReviewVerdict(BaseModel):
    passed: bool
    issues: list[str]
    defect_category: DefectCategory = "none"


class GeminiReviewAgent(BaseGeminiAgent):
    error_cls = ReviewAgentError
    ESTIMATED_COST_USD = 0.02

    def __init__(
        self,
        model_name: str = "gemini-3.6-flash",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
        log_path=None,
    ):
        super().__init__(model_name, api_key, client, base_url, log_path)

    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
        try:
            image_bytes = Path(candidate.image_url).read_bytes()
        except OSError as exc:
            raise self.error_cls(f"Could not read candidate image at {candidate.image_url!r}: {exc}") from exc
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        input_content = [
            {
                "type": "text",
                "text": (
                    "You are reviewing an AI-generated image for a game marketing video scene. "
                    f"The image was generated from this prompt: {prompts.image_prompt}\n"
                    "Judge whether the image faithfully matches the prompt. Respond with passed=true "
                    "only if the image clearly matches; otherwise passed=false and list concrete issues.\n\n"
                    "Two things below are hard requirements, not a matter of degree — treat "
                    "either one as a blocking failure even if it seems partial or 'slight', and "
                    "never pass an image with a known instance of either just because it is "
                    "otherwise a strong match for the prompt.\n\n"
                    "1. Perspective consistency: if the prompt specifies a first-person/"
                    "point-of-view shot, any visible face, helmet, or full body of the subject "
                    "that would not be visible from their own eyes is a blocking issue.\n\n"
                    "2. Physical integrity: any equipment, weapon, vehicle, or other rigid "
                    "object must read as one coherent, continuous physical object — reject it if "
                    "it appears bent, kinked, melted, or disconnected in a way that would not "
                    "hold together in reality. Likewise reject malformed anatomy — extra or "
                    "missing fingers, warped joints, or limbs merging unnaturally into held "
                    "objects or equipment.\n\n"
                    "Two things above are hard requirements, not a matter of degree. Two "
                    "things below are approximate, not exact — evaluate them more leniently "
                    "than everything else:\n\n"
                    "1. Shot distance (e.g. extreme close-up vs. medium vs. wide): pass as "
                    "long as the image is in the same broad category as requested — any "
                    "tight/close framing satisfies an extreme-close-up or close-up request, "
                    "any mid-range framing satisfies a medium-shot request, and so on. Reject "
                    "only for a clearly different category (e.g. a wide establishing shot "
                    "when a close-up was requested), not for a shot that is merely tighter or "
                    "looser than the exact label implies.\n\n"
                    "2. Prop/weapon orientation (e.g. held vertically vs. resting on a "
                    "shoulder): pass as long as the pose is a reasonable, plausible "
                    "execution of the general idea — reject only for a starkly wrong "
                    "orientation (e.g. upside-down, pointed back at its own wielder, or a pose that "
                    "contradicts the described action), not for an angle that simply doesn't "
                    "match the exact description.\n\n"
                    "These two are evaluated separately from — and more leniently than — "
                    "every other aspect of prompt fidelity (subject appearance, color "
                    "palette, setting, everything else), which still needs to clearly match "
                    "as before.\n\n"
                    "If passed=false, also classify what kind of fix the defect needs, as "
                    "defect_category:\n"
                    "- 'localized_artifact': the image is otherwise correct and the problem is "
                    "confined to one small, isolated region (a stray mark, a texture glitch, a "
                    "small wrong detail) that could be fixed by editing just that region without "
                    "touching the rest of the image.\n"
                    "- 'structural_geometry': the defect is load-bearing on how the whole image "
                    "was composed — a bent or kinked or disconnected object, malformed anatomy, "
                    "perspective/POV mixing, or a subject/setting mismatch. Editing one region "
                    "cannot fix this; the image needs to be regenerated from scratch.\n"
                    "If passed=true, use defect_category='none'. When genuinely unsure whether an "
                    "issue is localized or structural, choose 'structural_geometry' — it is the "
                    "safer default."
                ),
            },
            {"type": "image", "data": image_b64, "mime_type": mime_type_for_image_path(candidate.image_url)},
        ]

        verdict = self._structured_interaction(input_content, ReviewVerdict)
        return ConsistencyReview(
            reviewed_by=self.model_name,
            passed=verdict.passed,
            issues=verdict.issues,
            defect_category=verdict.defect_category,
        )

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
