// workmate-agent `/api/v1/*` 응답 계약과 1:1로 맞춘 타입.
// `workmate-ui/lib/workmate-types.ts`에서 그대로 이식(19번 문서 2단계).
// 근거: ../workmate-agent/app/task_api.py, meeting_api.py, internal_chat.py,
//       docs/schemas/workmate-skill-schemas.schema.json

export type TaskStatus = "todo" | "in_progress" | "blocked" | "done" | "cancelled";

// 승인된 Action Item Task에만 붙는 읽기 전용 회의 근거. `evidence_text`는
// 서버가 원문에서 추출한 값이라 여기서도 항상 읽기 전용이다 — 수정은
// 회의 관리(Archive.tsx)의 Action Item 수정에서만.
export type TaskMeetingEvidence = {
  meeting_id: string;
  meeting_title: string;
  action_item_id: string;
  evidence_text: string;
  meeting_chunk_id: string | null;
};

export type Task = {
  task_id: string;
  assignee_user_id: string;
  title: string;
  status: TaskStatus;
  priority_hint: number | null;
  due_at: string | null;
  source_type: string;
  source_id: string | null;
  deleted_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  meeting_evidence: TaskMeetingEvidence | null;
};

export type Meeting = {
  meeting_id: string;
  user_id: string;
  title: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string | null;
  has_analysis: boolean;
};

export type RecordingMeta = {
  recording_id: string;
  meeting_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  object_key: string | null;
};

export type TranscriptRow = {
  transcript_id: string;
  meeting_id: string;
  chunk_no: number;
  text: string;
  is_final: 0 | 1;
  start_ms: number | null;
  end_ms: number | null;
  created_at: string;
};

export type ActionItem = {
  action_item_id: string;
  title: string;
  description: string | null;
  assignee_user_id: string | null;
  due_at: string | null;
  approval_status: "pending" | "approved" | "rejected";
  confidence: number;
  evidence_span: { meeting_chunk_ids: string[]; start_ms: number; end_ms: number };
  evidence_text: string;
};

export type PriorityScoreBreakdown = {
  deadline: number;
  importance: number;
  blocked_or_overdue: number;
  meeting_commitment: number;
  calendar_relevance: number;
};

export type PriorityItem = {
  rank: number;
  task_id: string;
  title: string;
  score: number;
  score_breakdown?: PriorityScoreBreakdown;
  reasons: string[];
};

export type CalendarItem = { event_id: string; title: string; starts_at: string; ends_at: string; related_task_ids?: string[] };
export type ImportantSignal = { type: string; source_id: string; summary: string; related_task_ids?: string[] };

export type DailyBriefingResult = {
  date: string;
  summary: string;
  calendar_events: CalendarItem[];
  important_signals: ImportantSignal[];
  priorities: PriorityItem[];
  source_refs: string[];
};

export type PriorityChange = {
  task_id: string;
  change_type: "entered" | "moved_up" | "moved_down" | "removed" | "unchanged";
  previous_rank: number | null;
  current_rank: number | null;
  reason: string;
};

export type PriorityRankingResult = {
  calculated_at: string;
  priorities: PriorityItem[];
  changes: PriorityChange[];
  source_refs: string[];
};

export type WorkItem = { task_id: string; title: string; status: TaskStatus; summary: string | null; due_at: string | null; source_refs: string[] };
export type PlanItem = { title: string; kind: "planned" | "carry_over" | "suggestion"; source_refs: string[] };

export type WeeklyReportResult = {
  period: { start: string; end: string };
  summary: string;
  completed: WorkItem[];
  in_progress: WorkItem[];
  delayed: WorkItem[];
  unresolved_issues: WorkItem[];
  next_week_plans: PlanItem[];
  source_refs: string[];
};

export type MeetingAnalysisResult = {
  meeting_id: string;
  summary: string;
  action_items: ActionItem[];
  transcript_ref: string;
  source_refs: string[];
};

export type MeetingSource = {
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  speaker: string | null;
  meeting_chunk_id: string;
  quote: string;
};

export type GroundedAnswerResult = {
  answer: string;
  sources: MeetingSource[];
  insufficient_evidence: boolean;
};

export type SkillWarning = { source: string; code: string; message: string; retryable: boolean; last_success_at: string | null };

export type TypedSkillResult =
  | { type: "daily_briefing"; data: DailyBriefingResult }
  | { type: "priority_ranking"; data: PriorityRankingResult }
  | { type: "weekly_report"; data: WeeklyReportResult }
  | { type: "meeting_analysis"; data: MeetingAnalysisResult }
  | { type: "grounded_answer"; data: GroundedAnswerResult };

export type SkillChatArtifact = {
  name: string;
  description: string;
  text: string;
  data: TypedSkillResult | null;
  markdown: string | null;
  mock: boolean;
  business_result: boolean;
};

export type SkillChatResponse = {
  skill_id: string;
  task_id: string;
  state: string;
  artifact: SkillChatArtifact;
  warnings: SkillWarning[];
};

// `GET /api/v1/internal/skill-chat/tasks/{task_id}`(A2A `Task` Snapshot 원형,
// camelCase — `json_format.MessageToDict` 기본값). `analyze_meeting`의 비동기
// Polling 응답이다.
export type SkillChatTaskState = "TASK_STATE_SUBMITTED" | "TASK_STATE_WORKING" | "TASK_STATE_COMPLETED" | "TASK_STATE_FAILED" | "TASK_STATE_CANCELED" | "TASK_STATE_REJECTED" | string;

export type SkillChatTaskSnapshot = {
  id: string;
  status: {
    state: SkillChatTaskState;
    message?: { parts?: { text?: string }[] };
  };
  artifacts?: {
    artifactId: string;
    name?: string;
    description?: string;
    metadata?: { mock?: boolean; business_result?: boolean; warnings?: SkillWarning[] };
    parts?: { text?: string }[];
  }[];
};

// 근거: app/proposal_api.py (TaskProposal.as_payload, review 응답)
export type ProposalSourceType = "email" | "calendar";

export type TaskProposal = {
  proposal_id: string;
  user_id: string;
  source_type: ProposalSourceType;
  source_id: string;
  title: string;
  assignee_user_id: string;
  due_at: string | null;
  priority_hint: number | null;
  metadata: Record<string, unknown> | null;
};

export type ProposalReviewResult = {
  decision: "approve" | "ignore";
  source_type: ProposalSourceType;
  source_id: string;
  created?: boolean;
  task?: Task;
};

export type SimilarTaskConflict = { code: "SIMILAR_TASK_EXISTS"; tasks: Task[] };

export type GmailSyncResponse = {
  fetched: number;
  published: { message_id: string; source_id: string; title: string }[];
  skipped: { message_id: string; reason: string }[];
  note: string;
};

export type CalendarSyncResponse = {
  fetched: number;
  published: { source_id: string; title: string }[];
  skipped: { source_id: string; reason: string }[];
  note: string;
};

export type GoogleConnectionStatus = { connected: boolean };
export type GoogleConnectionStart = { authorization_url: string };
