from ..schema import Scene, Prompts


class PromptAgent:
    def __init__(self, prompt_model: str = "gpt-5-mini"):
        self.prompt_model = prompt_model

    def run(self, scene: Scene, feedback: str | None = None) -> Prompts:
        sb = scene.storyboard
        image_prompt = f"{sb.setting}, {sb.subject}, {sb.action}, camera: {sb.camera}"
        video_motion_prompt = f"{sb.camera}, {sb.action}"
        return Prompts(image_prompt=image_prompt, video_motion_prompt=video_motion_prompt)

    def estimate_cost(self) -> float:
        return 0.0
