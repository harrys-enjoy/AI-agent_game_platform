// workmate-agent `/api/v1/*` 호출 경계.
// `workmate-ui/lib/workmate-api.ts`에서 이식하되(19번 문서 2단계), 인증 방식은
// 19번 문서 결정 5를 반영해 둘로 갈린다:
//
// - Task·Meeting·스킬챗(오늘 브리핑/주간 업무보고/할 일 관리/회의 녹음/회의 관리/
//   회의록 검색): `X-Workmate-Assignee` 헤더 하나로 충분하다 — 오케스트레이터가
//   이미 갖고 있는 "담당자" 선택(`assignee.ts`)을 그대로 쓴다. 값은 반드시
//   `encodeURIComponent`로 percent-encode해야 한다(HTTP 헤더 값은 비ASCII 문자를
//   못 담는다 — workmate-agent 쪽에서 실제로 확인·수정한 사항).
// - Gmail/Calendar 기반(제안함): 원래는 진짜 OIDC ID Token(Authorization: Bearer)이
//   필요했다(결정 5) — Google Cloud Console 접근 없이는 오케스트레이터에서 자동
//   재발급할 방법이 없어 "새로고침마다 토큰을 손으로 붙여넣는" UX가 그대로
//   남았다(7단계). 로컬 전용 프로젝트 서버라 다른 사람 PC에서 이름만으로 남의
//   메일을 열람할 위험을 감수 가능하다고 판단해(2026-08-19, 사용자 확인),
//   workmate-agent 쪽 `proposal_api.py`/`dev_gmail_sync_api.py`/
//   `dev_calendar_sync_api.py`/`google_oauth_web.py`를 `_authenticated_user_or_assignee`
//   로 옮겼다 — 이제 이 6개 API도 나머지와 똑같이 담당자 헤더만으로 충분하다.
//   실제 Gmail/Calendar 접근(OAuth Consent) 자체는 `googleAuthApi.start()`가 여는
//   진짜 구글 로그인 팝업으로 별도 처리된다 — "누구인지 증명"과 "메일 접근을
//   허락받는 것"은 다른 층이라, 이 완화는 전자에만 해당한다.
//
// 모듈 전역 상태를 두지 않고 매 호출마다 config를 인자로 받는다 — API Base URL은
// 로컬 개발에서만 바뀌는 값이라 상수로 두고, `assignee`는 호출부(App.tsx의
// `assigneeName` state)에서 매번 전달받는다.

import type {
  ActionItem,
  CalendarSyncResponse,
  GmailSyncResponse,
  GoogleConnectionStart,
  GoogleConnectionStatus,
  Meeting,
  MeetingAnalysisResult,
  ProposalReviewResult,
  RecordingMeta,
  SkillChatResponse,
  SkillChatTaskSnapshot,
  Task,
  TaskStatus,
  TranscriptRow,
} from "./types";

// 19번 문서 결정 3 — Windows 예약 포트 범위(7962-8061) 문제로 workmate-agent를
// 8100으로 옮긴 이력이 있다(`workmate-ui/lib/workmate-auth.tsx` 주석 참고).
export const WORKMATE_API_BASE_URL = "http://127.0.0.1:8100";

export type WorkmateConfig = { apiBase: string; assignee?: string; token?: string };

// 회의 녹음 WebSocket(`recording_stream.py`)은 `X-Workmate-Assignee` 헤더 경계
// 바깥에 있다 — `Sec-WebSocket-Protocol`의 `user.<user_id>`로 신원을 받는데, 이
// 값은 REST 쪽처럼 이름을 percent-encode해 보내는 게 아니라 **이미 해석된 고정
// `user_id`**여야 한다(그래야 `POST /api/v1/meetings`로 만든 회의와 같은
// `user_id`로 조회된다). 그래서 `workmate-agent/app/internal_chat.py`의
// `ASSIGNEE_TO_USER_ID`를 프론트에도 그대로 복제해 둔다 — 한쪽만 바뀌면 회의
// 녹음이 깨지니 두 파일을 같이 수정해야 한다.
export const ASSIGNEE_TO_USER_ID: Record<string, string> = {
  서선정: "10464531542706509691",
  배동우: "dev-assignee-video",
  이승현: "dev-assignee-develop",
  변해훈: "dev-assignee-gameqna",
};

export function resolveAssigneeUserId(assignee: string): string | null {
  return ASSIGNEE_TO_USER_ID[assignee] ?? null;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function assigneeHeaders(config: WorkmateConfig, extra: Record<string, string> = {}): Record<string, string> {
  if (!config.assignee?.trim()) {
    throw new ApiError("담당자를 선택하세요.", 0, null);
  }
  return { "X-Workmate-Assignee": encodeURIComponent(config.assignee), ...extra };
}

function oidcHeaders(config: WorkmateConfig, extra: Record<string, string> = {}): Record<string, string> {
  if (!config.token?.trim()) {
    throw new ApiError("Google 로그인이 필요합니다.", 0, null);
  }
  return { Authorization: `Bearer ${config.token}`, ...extra };
}

async function readJson(response: Response) {
  const raw = await response.text();
  let parsed: unknown;
  try {
    parsed = raw ? JSON.parse(raw) : null;
  } catch {
    parsed = raw;
  }
  if (!response.ok) {
    const detail = parsed && typeof parsed === "object" ? (parsed as { detail?: unknown }).detail ?? parsed : parsed;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new ApiError(`HTTP ${response.status}: ${message}`, response.status, detail);
  }
  return parsed;
}

async function apiFetch<T>(
  config: WorkmateConfig,
  auth: "assignee" | "oidc",
  path: string,
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {},
): Promise<T> {
  const authHeaderSet = auth === "assignee" ? assigneeHeaders(config, options.headers) : oidcHeaders(config, options.headers);
  const response = await fetch(`${config.apiBase}${path}`, {
    method: options.method ?? "GET",
    headers: {
      ...authHeaderSet,
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  return readJson(response) as Promise<T>;
}

async function apiUpload<T>(config: WorkmateConfig, path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${config.apiBase}${path}`, {
    method: "POST",
    headers: assigneeHeaders(config),
    body: formData,
  });
  return readJson(response) as Promise<T>;
}

// 인증이 필요 없는 순수 연결 확인 — 2단계의 "최소 동작 확인"이 이걸 쓴다.
export async function checkHealth(apiBase: string): Promise<{ ok: boolean; status: number }> {
  const response = await fetch(`${apiBase}/health/ready`);
  return { ok: response.ok, status: response.status };
}

/**
 * `text/event-stream` 응답을 직접 읽는다.
 *
 * 브라우저 표준 `EventSource`는 커스텀 헤더(Authorization·X-Workmate-Assignee 등)를
 * 전혀 보낼 수 없어 `/api/v1/notifications/stream`에는 애초에 쓸 수 없다 — 인증
 * 방식과 무관하게 유효한 이유다. 대신 `fetch` + `ReadableStream`으로 SSE 프레이밍을
 * 직접 파싱한다(7단계 제안함에서 사용).
 */
export async function streamSse(
  config: WorkmateConfig,
  auth: "assignee" | "oidc",
  path: string,
  onBlock: (block: string) => void,
  signal: AbortSignal,
  onOpen?: () => void,
): Promise<void> {
  const headers = auth === "assignee" ? assigneeHeaders(config) : oidcHeaders(config);
  const response = await fetch(`${config.apiBase}${path}`, { headers, signal });
  if (!response.ok || !response.body) {
    throw new ApiError(`HTTP ${response.status}: SSE 연결 실패`, response.status, null);
  }
  onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      if (block.trim()) onBlock(block);
    }
  }
}

export const proposalsApi = {
  reviewEmail: (config: WorkmateConfig, payload: { message_id: string; decision: "approve" | "ignore"; task?: unknown; allow_similar_duplicate?: boolean }, idempotencyKey: string) =>
    apiFetch<ProposalReviewResult>(config, "assignee", "/api/v1/email-task-proposals:review", { method: "POST", body: payload, headers: { "Idempotency-Key": idempotencyKey } }),
  reviewCalendar: (config: WorkmateConfig, payload: { calendar_id: string; event_id: string; decision: "approve" | "ignore"; task?: unknown; allow_similar_duplicate?: boolean }, idempotencyKey: string) =>
    apiFetch<ProposalReviewResult>(config, "assignee", "/api/v1/calendar-task-proposals:review", { method: "POST", body: payload, headers: { "Idempotency-Key": idempotencyKey } }),
};

export const devGmailSyncApi = {
  trigger: (config: WorkmateConfig, limit = 5) => apiFetch<GmailSyncResponse>(config, "assignee", `/api/v1/dev/gmail-sync?limit=${limit}`, { method: "POST" }),
};

export const devCalendarSyncApi = {
  trigger: (config: WorkmateConfig) => apiFetch<CalendarSyncResponse>(config, "assignee", "/api/v1/dev/calendar-sync", { method: "POST" }),
};

// 사용자가 "제안함" 화면에서 직접 자기 Google 계정을 연결하는 웹 OAuth 흐름
// (app/google_oauth_web.py). `start()`가 돌려주는 `authorization_url`을 컴포넌트가
// 팝업(`window.open`)으로 연다 — "누구인지"는 이제 담당자 헤더로 충분하지만, 그
// 흐름 자체(Google 로그인 화면 진입)는 여전히 진짜 OAuth Consent다.
export const googleAuthApi = {
  status: (config: WorkmateConfig) => apiFetch<GoogleConnectionStatus>(config, "assignee", "/api/v1/auth/google/status"),
  start: (config: WorkmateConfig) => apiFetch<GoogleConnectionStart>(config, "assignee", "/api/v1/auth/google/start"),
  disconnect: (config: WorkmateConfig) => apiFetch<GoogleConnectionStatus>(config, "assignee", "/api/v1/auth/google/disconnect", { method: "POST" }),
};

export const skillChatApi = {
  send: (config: WorkmateConfig, skillId: string, input: Record<string, unknown>) =>
    apiFetch<SkillChatResponse>(config, "assignee", "/api/v1/internal/skill-chat/messages", { method: "POST", body: { skill_id: skillId, input } }),
  // `analyze_meeting`처럼 `state: "submitted"`로 즉시 응답하는 Skill의 진행 상태를
  // 확인한다 — A2A `Task` Snapshot 원형 그대로 돌아온다.
  getTask: (config: WorkmateConfig, taskId: string) =>
    apiFetch<SkillChatTaskSnapshot>(config, "assignee", `/api/v1/internal/skill-chat/tasks/${encodeURIComponent(taskId)}`),
};

export const tasksApi = {
  list: (config: WorkmateConfig, params: { status?: TaskStatus; due_before?: string; include_deleted?: boolean } = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.due_before) query.set("due_before", params.due_before);
    if (params.include_deleted) query.set("include_deleted", "true");
    const qs = query.toString();
    return apiFetch<Task[]>(config, "assignee", `/api/v1/tasks${qs ? `?${qs}` : ""}`);
  },
  create: (
    config: WorkmateConfig,
    payload: { title: string; status?: TaskStatus; priority_hint?: number | null; due_at?: string | null },
  ) => apiFetch<Task>(config, "assignee", "/api/v1/tasks", { method: "POST", body: { ...payload, source_type: "manual" } }),
  update: (config: WorkmateConfig, taskId: string, payload: Partial<Pick<Task, "title" | "status" | "priority_hint" | "due_at">>) =>
    apiFetch<Task>(config, "assignee", `/api/v1/tasks/${encodeURIComponent(taskId)}`, { method: "PATCH", body: payload }),
  remove: (config: WorkmateConfig, taskId: string) =>
    apiFetch<void>(config, "assignee", `/api/v1/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" }),
};

export const meetingsApi = {
  list: (config: WorkmateConfig) => apiFetch<Meeting[]>(config, "assignee", "/api/v1/meetings"),
  get: (config: WorkmateConfig, meetingId: string) => apiFetch<Meeting>(config, "assignee", `/api/v1/meetings/${encodeURIComponent(meetingId)}`),
  create: (config: WorkmateConfig, payload: { title: string; started_at?: string | null; meeting_id?: string }) =>
    apiFetch<Meeting>(config, "assignee", "/api/v1/meetings", { method: "POST", body: payload }),
  // Soft Delete — 목록·상세 조회에서 더는 보이지 않는다.
  delete: (config: WorkmateConfig, meetingId: string) =>
    apiFetch<void>(config, "assignee", `/api/v1/meetings/${encodeURIComponent(meetingId)}`, { method: "DELETE" }),
  transcript: (config: WorkmateConfig, meetingId: string) =>
    apiFetch<TranscriptRow[]>(config, "assignee", `/api/v1/meetings/${encodeURIComponent(meetingId)}/transcript`),
  uploadRecording: (config: WorkmateConfig, meetingId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiUpload<RecordingMeta>(config, `/api/v1/meetings/${encodeURIComponent(meetingId)}/recordings`, form);
  },
  approveAction: (config: WorkmateConfig, meetingId: string, actionItemId: string, payload: { title: string; evidence_text: string }) =>
    apiFetch<{ action_item_id: string; approval_status: string; task_id: string; idempotent: boolean }>(
      config,
      "assignee",
      `/api/v1/meetings/${encodeURIComponent(meetingId)}/actions/${encodeURIComponent(actionItemId)}/approve`,
      { method: "POST", body: payload },
    ),
  // `analyze_meeting`이 저장해 둔 요약·Action Item을 재조회한다 — 다시 분석을
  // 돌리지 않는다. `analyze_meeting`이 비동기 Task로 완료된 뒤 최종 결과를
  // 가져오는 용도로도 쓴다.
  getAnalysis: (config: WorkmateConfig, meetingId: string) =>
    apiFetch<MeetingAnalysisResult>(config, "assignee", `/api/v1/meetings/${encodeURIComponent(meetingId)}/analysis`),
  reviewActions: (
    config: WorkmateConfig,
    meetingId: string,
    decisions: { action_item_id: string; decision: "approve" | "edit" | "reject"; changes?: Record<string, unknown> }[],
  ) =>
    apiFetch<{ results: { action_item_id: string; decision: string; approval_status: string; task_id: string | null }[] }>(
      config,
      "assignee",
      `/api/v1/meetings/${encodeURIComponent(meetingId)}/actions:review`,
      { method: "POST", body: { decisions } },
    ),
};

export type { ActionItem };
