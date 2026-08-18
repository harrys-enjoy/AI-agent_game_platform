from pathlib import Path

from google import genai

from ..config import ModelConfig
from .gemini_director_agent import GeminiDirectorAgent
from .gemini_image_agent import GeminiImageAgent
from .gemini_image_edit_agent import GeminiImageEditAgent
from .gemini_planning_agent import GeminiPlanningAgent
from .gemini_prompt_agent import GeminiPromptAgent
from .gemini_review_agent import GeminiReviewAgent
from .gemini_storyboard_agent import GeminiStoryboardAgent


def build_real_agents(
    gemini_api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    gemini_client: genai.Client | None = None,
    log_path: str | Path | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": GeminiPlanningAgent(models.planning_model, api_key=gemini_api_key, client=gemini_client, log_path=log_path),
        "storyboard_agent": GeminiStoryboardAgent(models.storyboard_model, api_key=gemini_api_key, client=gemini_client, log_path=log_path),
        "prompt_agent": GeminiPromptAgent(models.prompt_model, api_key=gemini_api_key, client=gemini_client, log_path=log_path),
        "image_agent": GeminiImageAgent(models.image_model, output_dir=output_dir, api_key=gemini_api_key, client=gemini_client, log_path=log_path),
        "review_agent": GeminiReviewAgent(models.review_model, api_key=gemini_api_key, client=gemini_client, log_path=log_path),
        "director_agent": GeminiDirectorAgent(models.director_model, api_key=gemini_api_key, client=gemini_client, log_path=log_path),
        "image_edit_agent": GeminiImageEditAgent(
            models.image_edit_model, output_dir=output_dir, api_key=gemini_api_key, client=gemini_client, log_path=log_path
        ),
    }
