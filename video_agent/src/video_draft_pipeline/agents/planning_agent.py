from ..schema import Narrative, Beat, ProjectInput

BEAT_TEMPLATE: dict[str, tuple[str, str]] = {
    "setup": ("평화로운 상황 전개", "calm"),
    "conflict": ("사건 발생, 긴장감 고조", "tense"),
    "climax": ("절정, 핵심 비주얼 등장", "epic"),
    "resolution": ("마무리 및 브랜드 노출", "hype"),
}


class PlanningAgent:
    def __init__(self, planning_model: str = "gpt-5.4"):
        self.planning_model = planning_model

    def run(self, project_input: ProjectInput) -> Narrative:
        beats = [
            Beat(beat_id=beat_id, description=f"{project_input.brief}: {desc}", tone=tone)
            for beat_id, (desc, tone) in BEAT_TEMPLATE.items()
        ]
        return Narrative(beats=beats)

    def estimate_cost(self) -> float:
        return 0.0
