from ..schema import Narrative, ProjectInput, Scene, Storyboard


class StoryboardAgent:
    def __init__(self, storyboard_model: str = "gpt-5.4"):
        self.storyboard_model = storyboard_model

    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]:
        beats = narrative.beats

        if not beats:
            raise ValueError("StoryboardAgent requires at least one beat")

        n = len(beats)
        base = project_input.duration_sec / n

        scenes: list[Scene] = []
        for i, beat in enumerate(beats):
            duration = base if i < n - 1 else project_input.duration_sec - base * (n - 1)
            scenes.append(
                Scene(
                    scene_id=f"scene_{i + 1:02d}",
                    beat_id=beat.beat_id,
                    order=i + 1,
                    duration_sec=duration,
                    storyboard=Storyboard(
                        camera="슬로우 팬",
                        subject=project_input.brief,
                        action=beat.description,
                        setting=project_input.scene_type,
                        required_elements=(
                            list(project_input.brand_requirements)
                            if beat.beat_id == "resolution"
                            else []
                        ),
                    ),
                )
            )
        return scenes

    def estimate_cost(self) -> float:
        return 0.0
