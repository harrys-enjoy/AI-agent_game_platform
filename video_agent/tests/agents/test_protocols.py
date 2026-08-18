from video_draft_pipeline.agents.director_agent import DirectorAgent
from video_draft_pipeline.agents.image_agent import ImageAgent
from video_draft_pipeline.agents.image_edit_agent import ImageEditAgent
from video_draft_pipeline.agents.planning_agent import PlanningAgent
from video_draft_pipeline.agents.prompt_agent import PromptAgent
from video_draft_pipeline.agents.gemini_image_edit_agent import GeminiImageEditAgent
from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent
from video_draft_pipeline.agents.review_agent import ReviewAgent
from video_draft_pipeline.agents.protocols import (
    DirectorAgentProtocol,
    ImageAgentProtocol,
    ImageEditAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    ReviewAgentProtocol,
    StoryboardAgentProtocol,
)
from video_draft_pipeline.agents.storyboard_agent import StoryboardAgent
from video_draft_pipeline.agents.gemini_director_agent import GeminiDirectorAgent
from video_draft_pipeline.agents.gemini_image_agent import GeminiImageAgent
from video_draft_pipeline.agents.gemini_planning_agent import GeminiPlanningAgent
from video_draft_pipeline.agents.gemini_prompt_agent import GeminiPromptAgent
from video_draft_pipeline.agents.gemini_storyboard_agent import GeminiStoryboardAgent


def test_planning_agents_satisfy_protocol():
    assert isinstance(PlanningAgent(), PlanningAgentProtocol)


def test_storyboard_agents_satisfy_protocol():
    assert isinstance(StoryboardAgent(), StoryboardAgentProtocol)


def test_prompt_agents_satisfy_protocol():
    assert isinstance(PromptAgent(), PromptAgentProtocol)


def test_image_agents_satisfy_protocol(tmp_path):
    assert isinstance(ImageAgent(), ImageAgentProtocol)


def test_review_agents_satisfy_protocol():
    assert isinstance(ReviewAgent(), ReviewAgentProtocol)
    assert isinstance(GeminiReviewAgent(api_key="test-key"), ReviewAgentProtocol)


def test_director_agents_satisfy_protocol():
    assert isinstance(DirectorAgent(), DirectorAgentProtocol)


def test_image_edit_agents_satisfy_protocol(tmp_path):
    assert isinstance(ImageEditAgent(), ImageEditAgentProtocol)
    assert isinstance(
        GeminiImageEditAgent(api_key="test-key", output_dir=tmp_path / "media"), ImageEditAgentProtocol
    )


def test_gemini_planning_agent_satisfies_protocol():
    assert isinstance(GeminiPlanningAgent(api_key="test-key"), PlanningAgentProtocol)


def test_gemini_storyboard_agent_satisfies_protocol():
    assert isinstance(GeminiStoryboardAgent(api_key="test-key"), StoryboardAgentProtocol)


def test_gemini_prompt_agent_satisfies_protocol():
    assert isinstance(GeminiPromptAgent(api_key="test-key"), PromptAgentProtocol)


def test_gemini_image_agent_satisfies_protocol(tmp_path):
    assert isinstance(
        GeminiImageAgent(api_key="test-key", output_dir=tmp_path / "media"), ImageAgentProtocol
    )


def test_gemini_director_agent_satisfies_protocol():
    assert isinstance(GeminiDirectorAgent(api_key="test-key"), DirectorAgentProtocol)
