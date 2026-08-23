from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Preset = Literal["공개", "이벤트", "커뮤니티"]
SceneType = Literal["인게임", "스튜디오"]
BeatId = Literal["setup", "conflict", "climax", "resolution"]
RenderBackendName = Literal["veo-3.1-lite", "veo-3.1-fast", "veo-3.1-standard", "ltx-2-3-fast", "ltx-2-3-pro"]
RenderStatus = Literal["pending", "rendering", "done", "failed"]
Decision = Literal["accept", "regenerate", "reject"]
DefectCategory = Literal["none", "localized_artifact", "structural_geometry"]


class ProjectInput(BaseModel):
    preset: Preset
    scene_type: SceneType
    duration_sec: int = Field(gt=0, le=30)
    brief: str
    brand_requirements: list[str] = Field(default_factory=list)
    max_duration_sec: int = 30
    max_budget_usd: float = 5.00


class Beat(BaseModel):
    beat_id: BeatId
    description: str
    tone: str


class StyleGuide(BaseModel):
    visual_style: str = ""
    color_palette: str = ""
    subject_blueprint: str = ""
    secondary_subject_blueprint: str = ""


class Narrative(BaseModel):
    beats: list[Beat]
    style_guide: StyleGuide = Field(default_factory=StyleGuide)


class Storyboard(BaseModel):
    camera: str
    subject: str
    action: str
    setting: str
    visual_style: str = ""
    color_palette: str = ""
    secondary_subject: str = ""
    required_elements: list[str] = Field(default_factory=list)


class Prompts(BaseModel):
    image_prompt: str
    video_motion_prompt: str


class ConsistencyReview(BaseModel):
    reviewed_by: str
    passed: bool
    issues: list[str] = Field(default_factory=list)
    defect_category: DefectCategory = "none"


class DirectorDecision(BaseModel):
    decision: Decision
    feedback: str | None = None
    decided_by: str


class Candidate(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    candidate_id: str
    image_url: str
    generated_by: str
    consistency_review: ConsistencyReview | None = None
    director_decision: DirectorDecision | None = None


class RenderResult(BaseModel):
    backend: RenderBackendName
    status: RenderStatus
    clip_url: str | None = None
    cost_usd: float = 0.0


class Scene(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    scene_id: str
    beat_id: BeatId
    order: int
    duration_sec: float = Field(gt=0)
    storyboard: Storyboard
    prompts: Prompts | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    accepted_candidate_id: str | None = None
    needs_manual_fix: bool = False
    render: RenderResult | None = None
    retry_count: int = 0
    max_retries: int = 3


class Project(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    project_id: str
    input: ProjectInput
    narrative: Narrative | None = None
    scenes: list[Scene] = Field(default_factory=list)
    output_video_url: str | None = None
    running_cost_usd: float = 0.0
