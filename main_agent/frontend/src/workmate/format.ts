// 화면 렌더링에 쓰는 순수 함수만 모은다. React/DOM에 의존하지 않는다.
// `workmate-ui/lib/workmate-format.ts`에서 그대로 이식(19번 문서 2단계) — Next.js
// 의존이 없는 순수 모듈이라 수정 없이 옮길 수 있었다.

import type { TaskProposal, TaskStatus } from "./types";

/** ISO 문자열을 `YYYY-MM-DD HH:mm`으로 표시한다. 값이 없으면 대시를 반환한다. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** `YYYY-MM-DD`를 `days`만큼 옮긴다. 백엔드 `week_of`는 그 날짜가 속한 ISO
 * 주간(월요일~다음 월요일 전) 전체를 그대로 조회 범위로 쓴다 — ±7일만
 * 옮기면 항상 같은 요일의 다음/이전 주로 이동한다. */
export function shiftIsoDate(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** `now`의 로컬 날짜를 `YYYY-MM-DD`로 만든다. */
export function todayIsoDate(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** "주간 업무보고" 화면이 날짜를 따로 고르지 않았을 때 보여줄 기본 기간의
 * 시작일 — 오늘 기준 지난 1주("오늘-7일"). */
export function defaultWeeklyReportWeekOf(now: Date = new Date()): string {
  return shiftIsoDate(todayIsoDate(now), -7);
}

/** ISO 문자열을 `M월 D일`로 표시한다(브리핑/보고서 상단 문구용). */
export function formatKoreanDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

// 실제 Task 상태(5종)를 오케스트레이터 기존 목업 디자인의 배지 문구로 매핑한다.
const TASK_STATUS_BADGE: Record<TaskStatus, string> = {
  todo: "할 일",
  in_progress: "진행 중",
  blocked: "지연",
  done: "완료",
  cancelled: "취소",
};

export function taskStatusBadge(status: TaskStatus): string {
  return TASK_STATUS_BADGE[status] ?? status;
}

export function summarizeTaskCounts(tasks: { status: TaskStatus }[]): Record<TaskStatus, number> {
  const counts: Record<TaskStatus, number> = { todo: 0, in_progress: 0, blocked: 0, done: 0, cancelled: 0 };
  for (const task of tasks) {
    if (task.status in counts) counts[task.status] += 1;
  }
  return counts;
}

/** Skill Chat `input` 공통 필드. */
function baseSkillInput(skillId: string) {
  return { schema_version: "1.0" as const, skill_id: skillId, timezone: "Asia/Seoul", locale: "ko-KR" };
}

export function dailyBriefingInput() {
  return baseSkillInput("daily_briefing");
}

export function rankPrioritiesInput() {
  return { ...baseSkillInput("rank_priorities"), compare_with_previous: true };
}

// `week_of`(YYYY-MM-DD)를 생략하면 서버가 수신일이 속한 주간을 쓴다 — 지정하면
// 그 날짜가 속한 ISO 주간을 대신 조회한다.
export function weeklyReportInput(weekOf?: string) {
  return { ...baseSkillInput("weekly_report"), ...(weekOf ? { week_of: weekOf } : {}) };
}

export function analyzeMeetingInput(meetingId: string) {
  return { ...baseSkillInput("analyze_meeting"), meeting_id: meetingId };
}

export type SearchMeetingsFilters = { date_from?: string; date_to?: string; meeting_ids?: string[] };

// `filters`는 백엔드가 이미 지원하는 값만 보낸다. 빈 값(빈 문자열·빈 배열)은
// 아예 필드에서 빼 요청을 깔끔하게 유지한다.
export function searchMeetingsInput(query: string, limit = 5, filters?: SearchMeetingsFilters) {
  const cleaned = filters
    ? Object.fromEntries(Object.entries(filters).filter(([, value]) => (Array.isArray(value) ? value.length > 0 : Boolean(value))))
    : undefined;
  return {
    ...baseSkillInput("search_meetings"),
    query,
    limit,
    ...(cleaned && Object.keys(cleaned).length > 0 ? { filters: cleaned } : {}),
  };
}

export function getMeetingAnalysisInput(meetingId: string) {
  return { ...baseSkillInput("get_meeting_analysis"), meeting_id: meetingId };
}

export type ActionItemDecisionInput = { action_item_id: string; decision: "approve" | "edit" | "reject"; changes?: Record<string, unknown> };

export function reviewActionItemsInput(meetingId: string, decisions: ActionItemDecisionInput[]) {
  return { ...baseSkillInput("review_action_items"), meeting_id: meetingId, decisions };
}

export type ReviewProposalParams = {
  source_type: "email" | "calendar";
  decision: "approve" | "ignore";
  message_id?: string;
  calendar_id?: string;
  event_id?: string;
  task?: Record<string, unknown>;
  allow_similar_duplicate?: boolean;
};

export function reviewProposalInput(params: ReviewProposalParams) {
  return { ...baseSkillInput("review_proposal"), ...params };
}

/** priority_ranking의 `changes`에서 특정 Task의 순위 이동 배지 문구를 만든다. */
export function movementLabel(changeType: string | undefined, previousRank: number | null | undefined, currentRank: number | null | undefined): string | null {
  if (changeType === "moved_up" && previousRank && currentRank) return `↑ ${previousRank - currentRank}단계 상승`;
  if (changeType === "moved_down" && previousRank && currentRank) return `↓ ${currentRank - previousRank}단계 하락`;
  if (changeType === "entered") return "신규 진입";
  return null;
}

/** 자유 텍스트 검색 필터. Task 제목에 검색어가 포함되는지만 본다(대소문자 무시). */
export function matchesQuery(title: string, query: string): boolean {
  if (!query.trim()) return true;
  return title.toLowerCase().includes(query.trim().toLowerCase());
}

/**
 * `text/event-stream` 조각(빈 줄로 끝나는 하나의 이벤트 블록)을
 * `{event, data}`로 파싱한다. 여러 줄 `data:`는 줄바꿈으로 합친다.
 */
export function parseSseBlock(block: string): { event: string; data: unknown } | null {
  const lines = block.split("\n");
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return { event, data: raw };
  }
}

/** Calendar 제안의 `due_at`(일정 시작 시각)이 브라우저 로컬 날짜 기준 오늘인지
 * 확인한다. `due_at`이 없으면 안전하게 `false`를 반환한다. */
export function isCalendarProposalToday(proposal: Pick<TaskProposal, "due_at">, now: Date = new Date()): boolean {
  if (!proposal.due_at) return false;
  const eventDate = new Date(proposal.due_at);
  if (Number.isNaN(eventDate.getTime())) return false;
  return (
    eventDate.getFullYear() === now.getFullYear() &&
    eventDate.getMonth() === now.getMonth() &&
    eventDate.getDate() === now.getDate()
  );
}

/** Toast·데스크톱 알림을 띄울지 결정한다 — 출처별로 기준이 다르다: 이메일은
 * "마지막 동기화 이후 새로 온 것만", Calendar는 "당일 일정만". */
export function shouldToastProposal(
  proposal: Pick<TaskProposal, "source_type" | "due_at" | "metadata">,
  lastSyncAt: string | null,
  now: Date = new Date(),
): boolean {
  if (proposal.source_type === "calendar") return isCalendarProposalToday(proposal, now);
  if (proposal.source_type === "email") {
    if (!lastSyncAt) return false;
    const receivedAt = getProposalDisplayDate(proposal);
    if (!receivedAt) return false;
    const receivedTime = new Date(receivedAt).getTime();
    const cutoffTime = new Date(lastSyncAt).getTime();
    if (Number.isNaN(receivedTime) || Number.isNaN(cutoffTime)) return false;
    return receivedTime > cutoffTime;
  }
  return true;
}

/** 제안 카드에 보여줄 날짜 — 출처별로 값이 다른 곳에서 온다: 이메일은
 * `metadata.received_at`(수신 시각), Calendar는 `due_at`(일정 시작 시각). */
export function getProposalDisplayDate(proposal: Pick<TaskProposal, "source_type" | "due_at" | "metadata">): string | null {
  if (proposal.source_type === "email") {
    const receivedAt = (proposal.metadata as Record<string, unknown> | null)?.received_at;
    return typeof receivedAt === "string" ? receivedAt : null;
  }
  return proposal.due_at;
}

/** 제안 카드 목록을 정렬한다 — 1순위: 이메일 먼저, Calendar 나중. 2순위:
 * 이메일은 수신 날짜 내림차순(최신 먼저), Calendar는 일정 날짜 오름차순
 * (임박한 순). 날짜가 없는 항목은 그 출처 그룹 안에서 맨 뒤로 보낸다. */
export function sortProposals<T extends Pick<TaskProposal, "source_type" | "due_at" | "metadata">>(list: T[]): T[] {
  return [...list].sort((a, b) => {
    if (a.source_type !== b.source_type) return a.source_type === "email" ? -1 : 1;
    const aDate = getProposalDisplayDate(a);
    const bDate = getProposalDisplayDate(b);
    const aTime = aDate ? new Date(aDate).getTime() : NaN;
    const bTime = bDate ? new Date(bDate).getTime() : NaN;
    const aMissing = Number.isNaN(aTime);
    const bMissing = Number.isNaN(bTime);
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    return a.source_type === "email" ? bTime - aTime : aTime - bTime;
  });
}

// 이름 있는 Entity: HTML 표준의 극히 일부 — 메일 Snippet에서 실제로 보이는
// 것들만 다룬다.
const NAMED_HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

/**
 * Gmail Snippet 등 서버가 원문 그대로 준 텍스트에 남은 HTML Entity(예:
 * `&#39;`)를 사람이 읽기 좋은 문자로 되돌린다.
 */
export function decodeHtmlEntities(text: string): string {
  return text.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, entity: string) => {
    if (entity[0] === "#") {
      const codePoint = entity[1]?.toLowerCase() === "x" ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10);
      return Number.isNaN(codePoint) ? match : String.fromCodePoint(codePoint);
    }
    return NAMED_HTML_ENTITIES[entity] ?? match;
  });
}

/**
 * 서버가 최대 500자까지 그대로 줄 수 있는 값을 카드 한두 줄 미리보기로
 * 줄인다. 공백에서 자연스럽게 끊어 단어 중간이 잘리지 않게 한다.
 */
export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  const cut = text.slice(0, maxLength);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > maxLength * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
