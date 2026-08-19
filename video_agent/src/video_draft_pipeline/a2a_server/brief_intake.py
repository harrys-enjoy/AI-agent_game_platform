import re

from pydantic import BaseModel

from ..agents.gemini_agent_base import BaseGeminiAgent
from ..schema import Preset, SceneType


class BriefIntakeError(Exception):
    pass


class IntakeResult(BaseModel):
    brief: str | None = None
    preset: Preset | None = None
    scene_type: SceneType | None = None
    duration_sec: int | None = None
    max_budget_usd: float | None = None
    clarifying_question: str | None = None


_DURATION_RE = re.compile(r"(\d+)\s*초")
_BUDGET_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:달러|\$|usd)", re.IGNORECASE)
_PRESET_KEYWORDS: dict[str, Preset] = {"이벤트": "이벤트", "공개": "공개", "커뮤니티": "커뮤니티"}
_SCENE_TYPE_KEYWORDS: dict[str, SceneType] = {"인게임": "인게임", "스튜디오": "스튜디오"}


def extract_hints(text: str) -> dict[str, object]:
    hints: dict[str, object] = {}

    duration_match = _DURATION_RE.search(text)
    if duration_match:
        hints["duration_sec"] = int(duration_match.group(1))

    budget_match = _BUDGET_RE.search(text)
    if budget_match:
        hints["max_budget_usd"] = float(budget_match.group(1))

    for keyword, preset in _PRESET_KEYWORDS.items():
        if keyword in text:
            hints["preset"] = preset
            break

    for keyword, scene_type in _SCENE_TYPE_KEYWORDS.items():
        if keyword in text:
            hints["scene_type"] = scene_type
            break

    return hints


class BriefIntakeAgent(BaseGeminiAgent):
    error_cls = BriefIntakeError
    ESTIMATED_COST_USD = 0.02

    _DEFAULT_CLARIFYING_QUESTION = "어떤 영상을 만들고 싶으신지 조금 더 자세히 알려주시겠어요?"

    def __init__(
        self,
        model_name: str = "gemini-3.6-flash",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
        log_path=None,
    ):
        super().__init__(model_name, api_key, client, base_url, log_path)

    def run(self, text: str) -> IntakeResult:
        hints = extract_hints(text)
        hint_lines = "\n".join(f"- {key}: {value}" for key, value in hints.items()) or "(none found)"
        input_content = [
            {
                "type": "text",
                "text": (
                    "You are the intake step for a game marketing video draft generator. "
                    "A user sent this free-text Korean request:\n\n"
                    f"{text}\n\n"
                    "A regex pre-pass found these literal hints (use them if present, they "
                    "are reliable, but they may be incomplete):\n"
                    f"{hint_lines}\n\n"
                    "Decide if this is a usable creative brief for a short game marketing "
                    "video. If it clearly describes what to advertise or promote (a "
                    "character, event, product, game moment, etc.), fill in `brief` with a "
                    "concise Korean brief summarizing it, plus `preset` (공개/이벤트/"
                    "커뮤니티), `scene_type` (인게임/스튜디오), `duration_sec`, and "
                    "`max_budget_usd` if you can infer them (use the hints, or reasonable "
                    "defaults — 이벤트/인게임/10초 — if genuinely unclear on those specific "
                    "fields, as long as the core subject of the video is clear). Only if "
                    "the request gives no usable subject at all (e.g. just a greeting, or "
                    "something entirely unrelated to a video request) set "
                    "`clarifying_question` instead: a short, friendly Korean question "
                    "asking what they want the video to be about. Never set both."
                ),
            }
        ]
        result = self._structured_interaction(input_content, IntakeResult)
        if not result.brief and not result.clarifying_question:
            result.clarifying_question = self._DEFAULT_CLARIFYING_QUESTION
        return result

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
