import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { UiVariant } from "./ui-variant";
import { quickActions } from "./ui-variant";
// 19번 문서 3단계 — 회의록 검색을 실데이터로 이식.
// 22번 문서 — 오늘 브리핑·주간 업무보고를 `workmate-ui` 원본과 필드 단위로 대조해
// (경고 배너·소스 상태·배점 내역 포함) 다시 실데이터로 이식(2026-08-19).
import { useSkillRunner, usePollingSkillRunner } from "./workmate/use-skill";
import {
  analyzeMeetingInput,
  dailyBriefingInput,
  decodeHtmlEntities,
  defaultWeeklyReportWeekOf,
  formatDateTime,
  formatKoreanDate,
  matchesQuery,
  movementLabel,
  rankPrioritiesInput,
  searchMeetingsInput,
  shiftIsoDate,
  summarizeTaskCounts,
  taskStatusBadge,
  truncateText,
  weeklyReportInput,
} from "./workmate/format";
import type { ActionItem, DailyBriefingResult, GroundedAnswerResult, Meeting, MeetingAnalysisResult, PlanItem, PriorityRankingResult, PriorityScoreBreakdown, SkillWarning, Task, TaskStatus, TranscriptRow, WeeklyReportResult, WorkItem } from "./workmate/types";
// 19번 문서 4단계 — 할 일 관리(`/api/v1/tasks` CRUD) 실데이터 이식.
import { ApiError, devCalendarSyncApi, devGmailSyncApi, googleAuthApi, meetingsApi, resolveAssigneeUserId, tasksApi, WORKMATE_API_BASE_URL, type WorkmateConfig } from "./workmate/api";
// 19번 문서 6단계 — 회의 녹음(REST 생성·업로드 + 실시간 WebSocket) 실데이터 이식.
import { Pcm16ChunkBuffer, STT_SAMPLE_RATE, float32ToPcm16, pcm16ToBase64, resampleLinear } from "./workmate/audio-pcm16";
// 19번 문서 7단계 — 제안함(SSE + Gmail/Calendar 동기화 + 승인/무시) 실데이터 이식.
// 이 화면만 진짜 Google OIDC ID Token이 필요하다(19번 문서 결정 5 — Gmail/Calendar는
// 우회 대상이 아니다).
import { ProposalNotificationsProvider, useProposalNotifications } from "./workmate/proposal-notifications";
import { reviewProposal } from "./workmate/proposal-review";
import { getProposalDisplayDate, sortProposals } from "./workmate/format";
import type { TaskProposal } from "./workmate/types";

export function PoliciesPanel() {
  return <section className="policies-card"><div className="policies-heading"><div><p className="eyebrow">MAIN AGENT / POLICIES</p><h2>Company Policies</h2><p>팀에서 자주 확인하는 사규와 운영 기준을 한곳에서 확인하세요.</p></div><input aria-label="Search company policies" placeholder="Search policies" /></div><div className="policy-grid"><article><span>01</span><h3>근무 및 휴가</h3><p>근무시간, 휴가, 재택근무 기준</p></article><article><span>02</span><h3>보안 및 개인정보</h3><p>정보보호와 데이터 취급 기준</p></article><article><span>03</span><h3>업무 운영</h3><p>회의, 승인, 협업 운영 기준</p></article><article><span>04</span><h3>복지 및 지원</h3><p>구성원 지원 제도와 이용 안내</p></article></div></section>;
}

export function QuickActions({ variant, currentChat, onSelect }: { variant: UiVariant; currentChat: string; onSelect: (prompt: string) => void }) {
  if (variant !== "updated" || currentChat !== "Workmate AI") return null;
  return <div className="quick-actions" aria-label="Workmate AI quick actions">{quickActions.map((action) => <button type="button" className="quick-action" key={action.id} onClick={() => onSelect(action.prompt)}><span className="quick-action-icon">↗</span><span><strong>{action.label}</strong><small>{action.prompt}</small></span></button>)}</div>;
}

export function TaskQuickActions({ variant, currentChat, onSelect, assigneeName, onRecordingChange }: { variant: UiVariant; currentChat: string | null; onSelect: (prompt: string) => void; assigneeName: string; onRecordingChange?: (recording: boolean) => void }) {
  // 19번 문서 결정 4 — 녹음 중 다른 탭으로 이동하면 WebSocket이 끊겨 서버가 그
  // 시점까지 받은 Chunk로 세션을 자동 확정한다. 이동 자체는 막지 않고, 확인창으로
  // 미리 알린다(사이드바 이동은 App.tsx가 같은 `onRecordingChange`로 따로 막는다).
  //
  // 이 컴포넌트는 `variant`/`currentChat` 조건에 따라 `null`을 반환할 수 있는데,
  // React Hooks 규칙상 모든 Hook은 조건부 반환보다 **먼저**, 매 렌더 항상 같은
  // 순서로 호출돼야 한다 — `cards`도 그 자체는 상수라 Hook보다 먼저 계산해 둔다
  // (기존 코드는 `useState(cards[0].id)`가 조건부 반환 *뒤에* 있어 `currentChat`이
  // 바뀌며 반환 전/후를 오갈 때 Hook 호출 개수가 렌더마다 달라지는 잠재적 버그였다
  // — 이번에 `isRecording` state를 추가하며 테스트가 이를 실제로 잡아냈다).
  const cards = [
    { ...quickActions[0], kicker: "TASKS", title: "할 일 관리", body: "직접 등록하거나 메일·일정·회의에서 승인한 업무입니다.", detail: "전체 12 · 진행 중 4 · 지연 2", action: "할 일 등록" },
    { ...quickActions[1], kicker: "NEW MEETING", title: "회의 녹음 및 분석", body: "실시간으로 녹음하거나 기존 파일을 업로드하세요.", detail: "MP3, WAV, M4A · 최대 500MB", action: "녹음 시작" },
    { ...quickActions[2], kicker: "MEETINGS", title: "회의 관리", body: "녹음, 회의록, 분석 결과를 회의별로 확인합니다.", detail: "QA 빌드 검토 회의 · 분석 대기", action: "새 회의" },
    { ...quickActions[3], kicker: "MEETING SEARCH", title: "이전 회의록 검색", body: "회의에서 결정된 내용을 근거와 함께 찾아드립니다.", detail: "QA 빌드 일정은 어느 회의에서 결정됐어?", action: "검색" },
    // 19번 문서 1단계 — 제안함(신규). 자리만 만들고 데이터는 아직 목업 유지(2·3단계에서 실데이터 이식).
    { ...quickActions[4], kicker: "PROPOSALS", title: "제안함", body: "Gmail·Calendar에서 들어온 제안을 검토합니다.", detail: "메일 2건 · 일정 1건 대기", action: "확인" },
  ];
  const [isRecording, setIsRecording] = useState(false);
  const handleRecordingChange = useCallback((recording: boolean) => { setIsRecording(recording); onRecordingChange?.(recording); }, [onRecordingChange]);
  const [selectedId, setSelectedId] = useState(cards[0].id);

  if (variant !== "updated" || currentChat !== "Workmate AI") return null;
  const selected = cards.find((card) => card.id === selectedId) ?? cards[0];
  function selectTab(card: (typeof cards)[number]) {
    if (isRecording && card.id !== selected.id && !window.confirm("녹음 중입니다. 이동하면 녹음이 종료됩니다. 이동할까요?")) return;
    setSelectedId(card.id);
    onSelect(card.prompt);
  }
  return <section className="task-quick-actions" aria-label="Workmate AI 업무 기능"><nav className="workmate-tabs">{cards.map((card) => <button type="button" className={card.id === selected.id ? "active" : ""} key={card.id} onClick={() => selectTab(card)}>{card.title}</button>)}</nav>{selected.id === "tasks" ? <TaskDetailPanel assigneeName={assigneeName} /> : selected.id === "recording" ? <RecordingDetailPanel assigneeName={assigneeName} onRecordingChange={handleRecordingChange} /> : selected.id === "meetings" ? <MeetingsDetailPanel assigneeName={assigneeName} /> : selected.id === "minutes" ? <MeetingSearchDetailPanel assigneeName={assigneeName} /> : <ProposalsDetailPanel assigneeName={assigneeName} />}</section>;
}

const MAIN_CHAT_API = "http://127.0.0.1:8000";
type MainRoute = {
  targetAgent: string;
  targetChat: string;
  originalRequest: string;
  handoff: "automatic" | "confirmation_required";
};

export function MainBriefingChatbot({ contextHint, owner = window.localStorage.getItem("main-assignee") ?? "default" }: { contextHint?: string; owner?: string } = {}) {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const composerInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    fetch(`${MAIN_CHAT_API}/api/chats/Main%20Chatbot/session?owner=${encodeURIComponent(owner)}`)
      .then((response) => response.ok ? response.json() as Promise<{ messages: { role: "user" | "assistant"; content: string }[] }> : Promise.reject(new Error("history failed")))
      .then((session) => { if (!cancelled) setMessages(session.messages.map((item) => ({ role: item.role, text: item.content }))); })
      .catch(() => { if (!cancelled) setMessages([]); });
    return () => { cancelled = true; };
  }, [owner]);

  function persist(role: "user" | "assistant", content: string) {
    void fetch(`${MAIN_CHAT_API}/api/chats/Main%20Chatbot/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role, content, owner }) }).catch(() => undefined);
  }

  async function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    const request = message.trim();
    if (!request || busy) return;
    setMessage("");
    setMessages((items) => [...items, { role: "user", text: request }]);
    persist("user", request);
    setBusy(true);
    try {
      const response = await fetch(`${MAIN_CHAT_API}/api/main-route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: request }),
      });
      if (!response.ok) throw new Error("Main route failed");
      const route = await response.json() as MainRoute;
      const answer = `${route.targetChat}로 연결합니다.`;
      setMessages((items) => [...items, { role: "assistant", text: answer }]);
      persist("assistant", answer);
      window.dispatchEvent(new CustomEvent("main-chat-route", {
        detail: { chat: route.targetChat, message: route.originalRequest, handoff: route.handoff },
      }));
    } catch {
      const answer = "담당 Agent를 판단하지 못했습니다. 다시 요청해 주세요.";
      setMessages((items) => [...items, { role: "assistant", text: answer }]);
      persist("assistant", answer);
    } finally { setBusy(false); }
  }

  return (
    <section className="briefing-chatbot">
      {contextHint ? (
        <h3>
          AI Chat · Video Generation
          <button className="reset-chat" type="button" onClick={() => { void fetch(`${MAIN_CHAT_API}/api/chats/Main%20Chatbot/reset?owner=${encodeURIComponent(owner)}`, { method: "POST" }).then(() => setMessages([])); }}>
            Reset chat
          </button>
        </h3>
      ) : (
        <h3>
          Main Chatbot <span>업무 라우터</span>
          <button className="reset-chat" type="button" onClick={() => { void fetch(`${MAIN_CHAT_API}/api/chats/Main%20Chatbot/reset?owner=${encodeURIComponent(owner)}`, { method: "POST" }).then(() => setMessages([])); }}>
            Reset chat
          </button>
        </h3>
      )}
      <div className="briefing-chat-messages">
        {messages.length === 0 && <p className="briefing-chat-empty">{contextHint ?? "간단한 질문이나 업무 내용을 입력하세요."}</p>}
        {messages.map((item, index) => (
          <p className={item.role === "user" ? "briefing-chat-user" : "briefing-chat-answer"} key={`${item.role}-${index}`}>
            {item.text}
          </p>
        ))}
        {busy && <p className="briefing-chat-answer">답변을 준비 중입니다…</p>}
      </div>
      <form className="briefing-chat-composer" onSubmit={submit}>
        <input
          ref={composerInputRef}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder={contextHint ? "Type a message..." : "무엇을 도와드릴까요?"}
        />
        {message && (
          <button
            type="button"
            className="clear-message"
            aria-label="입력 지우기"
            title="입력 지우기"
            onClick={() => { setMessage(""); composerInputRef.current?.focus(); }}
          >
            ✕
          </button>
        )}
        <button type="submit">➤</button>
      </form>
    </section>
  );
}

function ProposalsDetailPanel({ assigneeName }: { assigneeName: string }) {
  // 19번 문서 7단계 — 실데이터로 교체(2026-08-18). 원래 이 화면만 진짜 Google OIDC
  // ID Token(`Get-FreshIdToken.ps1`로 발급, 새로고침마다 재입력)이 필요했다(결정 5).
  // 로컬 전용 프로젝트 서버라 다른 사람 PC에서 이름만으로 남의 메일을 열람할 위험을
  // 감수 가능하다고 판단해(2026-08-19, 사용자 확인) 나머지 6개 화면과 같은 담당자
  // 헤더 인증으로 완화했다 — workmate-agent 쪽 `_authenticated_user_or_assignee`
  // 전환(`app/proposal_api.py` 등)과 짝을 이룬다. 자세한 트레이드오프는
  // `workmate/api.ts` 상단 주석 참고.
  const config: WorkmateConfig = { apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName };
  return <ProposalNotificationsProvider config={config}><ProposalsInner config={config} /></ProposalNotificationsProvider>;
}

function ProposalsInner({ config }: { config: WorkmateConfig }) {
  const { proposals, connected, connectError, toasts, dismissToast, desktopPermission, requestDesktopPermission, markAllSeen, removeProposal, unseenCount } = useProposalNotifications();
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const [calendarSyncing, setCalendarSyncing] = useState(false);
  const [calendarSyncNote, setCalendarSyncNote] = useState<string | null>(null);
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [googleConnecting, setGoogleConnecting] = useState(false);
  const [googleError, setGoogleError] = useState<string | null>(null);

  useEffect(() => {
    markAllSeen();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposals.length]);

  useEffect(() => {
    googleAuthApi.status(config).then((response) => setGoogleConnected(response.connected)).catch(() => setGoogleConnected(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function connectGoogleAccount() {
    setGoogleConnecting(true);
    setGoogleError(null);
    try {
      const response = await googleAuthApi.start(config);
      const popup = window.open(response.authorization_url, "workmate-google-connect", "width=520,height=720");
      if (!popup) {
        setGoogleError("팝업이 차단됐습니다. 브라우저에서 이 사이트의 팝업을 허용한 뒤 다시 시도하세요.");
        setGoogleConnecting(false);
        return;
      }
      const poll = window.setInterval(() => {
        if (!popup.closed) return;
        window.clearInterval(poll);
        setGoogleConnecting(false);
        googleAuthApi.status(config).then((status) => setGoogleConnected(status.connected)).catch(() => undefined);
      }, 500);
    } catch (err) {
      setGoogleError(err instanceof ApiError ? err.message : `연결 시작 실패: ${(err as Error).message}`);
      setGoogleConnecting(false);
    }
  }

  async function disconnectGoogleAccount() {
    setGoogleConnecting(true);
    setGoogleError(null);
    try {
      await googleAuthApi.disconnect(config);
      setGoogleConnected(false);
    } catch (err) {
      setGoogleError(err instanceof ApiError ? err.message : `연결 해제 실패: ${(err as Error).message}`);
    } finally {
      setGoogleConnecting(false);
    }
  }

  async function runGmailSync() {
    setSyncing(true);
    setSyncNote(null);
    try {
      const response = await devGmailSyncApi.trigger(config, 5);
      const skippedNote = response.skipped.length ? ` (${response.skipped.length}건은 분석 실패로 건너뜀)` : "";
      setSyncNote(`메일 ${response.fetched}건 분석 → 할 일 후보 ${response.published.length}건 발행됨${skippedNote}. ${response.note}`);
    } catch (err) {
      setSyncNote(err instanceof ApiError ? err.message : `동기화 실패: ${(err as Error).message}`);
    } finally {
      setSyncing(false);
    }
  }

  async function runCalendarSync() {
    setCalendarSyncing(true);
    setCalendarSyncNote(null);
    try {
      const response = await devCalendarSyncApi.trigger(config);
      const skippedNote = response.skipped.length ? ` (${response.skipped.length}건은 제외됨)` : "";
      setCalendarSyncNote(`일정 ${response.fetched}건 확인 → 할 일 후보 ${response.published.length}건 발행됨${skippedNote}. ${response.note}`);
    } catch (err) {
      setCalendarSyncNote(err instanceof ApiError ? err.message : `동기화 실패: ${(err as Error).message}`);
    } finally {
      setCalendarSyncing(false);
    }
  }

  return <article className="proposals-detail">
    {/* 24번 문서 5번 — `unseenCount`는 계산만 되고 어디에도 안 그려지던 죽은 값이었다.
        workmate-ui는 Shell 상단 종(`.bell`) 배지로 탭 밖에서도 보여주지만, 오케스트레이터는
        Provider가 이 탭 안에서만 마운트돼(23번 문서) 탭 밖에서 보여줄 위치가 없다 — 그
        구조 변경(Provider를 App.tsx Shell로 올리는 것)까지는 이번 범위가 아니라, 일단 이
        패널 진입 시 제목 옆에 배지로 보여준다. 진입 직후 `markAllSeen()`이 곧바로 읽음
        처리하므로 배지는 잠깐(첫 렌더~그 Effect가 도는 사이) 보였다가 사라진다. */}
    <div className="proposals-heading"><div><span className="feature-kicker">PROPOSALS</span><h1>제안함{unseenCount > 0 && <span style={{ marginLeft: 8, background: "#d66b34", color: "#fff", borderRadius: 10, fontSize: 11, fontWeight: 800, padding: "2px 7px", verticalAlign: "middle" }}>{unseenCount > 9 ? "9+" : unseenCount}</span>}</h1><p>Gmail·Calendar에서 발행된 임시 Task 제안을 실시간으로 받고 승인·무시합니다.</p></div></div>
    <div style={{ display: "flex", gap: 16, fontSize: 12, color: "#75867f", marginBottom: 12 }}>
      <span>● SSE {connected ? "연결됨" : "연결 안 됨"}</span>
      <span>● 데스크톱 알림 {desktopPermission === "granted" ? "허용됨" : desktopPermission === "unsupported" ? "미지원" : "꺼짐"}</span>
      {desktopPermission !== "granted" && desktopPermission !== "unsupported" && <button type="button" style={{ fontSize: 11 }} onClick={requestDesktopPermission}>데스크톱 알림 켜기</button>}
    </div>
    {connectError && <p style={{ color: "#bd655b" }}>{connectError}</p>}
    <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 16, background: "#fff", border: "1px solid #dfe7e1", borderRadius: 12, marginBottom: 12 }}>
      <div><b style={{ fontSize: 13 }}>Google 계정 연결</b><p style={{ margin: "4px 0 0", color: "#75867f", fontSize: 12 }}>{googleConnected === null ? "연결 상태 확인 중..." : googleConnected ? "내 Google 계정이 연결돼 있습니다." : "연결하지 않아도 개발 환경 공유 계정이 있으면 동기화가 그대로 동작합니다."}</p></div>
      {googleConnected === null ? <button type="button" style={{ marginLeft: "auto" }} disabled>확인 중...</button> : googleConnected ? <button type="button" style={{ marginLeft: "auto" }} disabled={googleConnecting} onClick={disconnectGoogleAccount}>{googleConnecting ? "처리 중..." : "연결 해제"}</button> : <button type="button" style={{ marginLeft: "auto" }} disabled={googleConnecting} onClick={connectGoogleAccount}>{googleConnecting ? "이동 중..." : "Google 계정 연결"}</button>}
    </div>
    {googleError && <p style={{ color: "#bd655b" }}>{googleError}</p>}
    <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 16, background: "#fff", border: "1px solid #dfe7e1", borderRadius: 12, marginBottom: 12 }}>
      <div><b style={{ fontSize: 13 }}>Gmail 동기화 테스트</b><p style={{ margin: "4px 0 0", color: "#75867f", fontSize: 12 }}>최근 메일 5건을 LLM으로 분석해 할 일 후보를 만듭니다.</p></div>
      <button type="button" style={{ marginLeft: "auto" }} disabled={syncing} onClick={runGmailSync}>{syncing ? "동기화 중..." : "Gmail 동기화 실행"}</button>
    </div>
    {syncNote && <p style={{ fontSize: 12, background: "#f4f6fa", padding: 12, borderRadius: 8 }}>{syncNote}</p>}
    <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 16, background: "#fff", border: "1px solid #dfe7e1", borderRadius: 12, marginBottom: 12 }}>
      <div><b style={{ fontSize: 13 }}>Calendar 동기화 테스트</b><p style={{ margin: "4px 0 0", color: "#75867f", fontSize: 12 }}>다가오는 일정 중 신규·확정 건만 제안으로 만듭니다.</p></div>
      <button type="button" style={{ marginLeft: "auto" }} disabled={calendarSyncing} onClick={runCalendarSync}>{calendarSyncing ? "동기화 중..." : "Calendar 동기화 실행"}</button>
    </div>
    {calendarSyncNote && <p style={{ fontSize: 12, background: "#f4f6fa", padding: 12, borderRadius: 8 }}>{calendarSyncNote}</p>}
    <div className="proposal-list">
      {sortProposals(proposals).map((proposal) => <ProposalCard key={proposal.proposal_id} proposal={proposal} config={config} onResolved={() => removeProposal(proposal.proposal_id)} />)}
      {!proposals.length && <p style={{ color: "#75867f" }}>아직 도착한 제안이 없습니다. 위 &lsquo;Gmail 동기화 실행&rsquo;·&lsquo;Calendar 동기화 실행&rsquo;을 눌러보세요.</p>}
    </div>
    <div style={{ position: "fixed", top: 16, right: 16, display: "flex", flexDirection: "column", gap: 8, zIndex: 100 }}>
      {toasts.map((toast) => <div key={toast.id} onClick={() => dismissToast(toast.id)} style={{ cursor: "pointer", background: "#19352c", color: "#fff", padding: "10px 14px", borderRadius: 8, fontSize: 12, maxWidth: 280 }}>새 제안: {toast.proposal.title}</div>)}
    </div>
  </article>;
}

function ProposalCard({ proposal, config, onResolved }: { proposal: TaskProposal; config: WorkmateConfig; onResolved: () => void }) {
  const [title, setTitle] = useState(proposal.title);
  const [assignee, setAssignee] = useState(proposal.assignee_user_id);
  const [dueAt, setDueAt] = useState(proposal.due_at ? proposal.due_at.slice(0, 16) : "");
  const [priority, setPriority] = useState(proposal.priority_hint?.toString() ?? "");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<Task[] | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function review(decision: "approve" | "ignore", allowSimilarDuplicate = false) {
    setBusy(true);
    setError(null);
    const task = decision === "approve" ? { title: title.trim(), assignee_user_id: assignee.trim(), due_at: dueAt ? new Date(dueAt).toISOString() : null, priority_hint: priority === "" ? null : Number(priority) } : undefined;
    try {
      const response = await reviewProposal(config, proposal, decision, task, allowSimilarDuplicate);
      setResult(response.decision === "ignore" ? "무시했습니다." : `Task ${response.created ? "생성" : "재사용"}: ${response.task?.task_id ?? ""}`);
      setConflict(null);
      setTimeout(onResolved, 1200);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && (err.detail as { code?: string } | null)?.code === "SIMILAR_TASK_EXISTS") {
        setConflict((err.detail as { tasks: Task[] }).tasks);
      } else {
        setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return <div style={{ padding: 16, background: "#fff", border: "1px solid #dfe7e1", borderRadius: 12, marginBottom: 10 }}>
    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 4 }}>
      <b style={{ fontSize: 11, color: "#397454" }}>{proposal.source_type === "email" ? "MAIL" : "CALENDAR"}</b>
      <b style={{ fontSize: 14 }}>{proposal.title}</b>
    </div>
    <p style={{ margin: "0 0 8px", fontSize: 11, color: "#75867f" }}>{proposal.source_type === "email" ? "수신" : "일정"}: {formatDateTime(getProposalDisplayDate(proposal))}</p>
    {/* 24번 문서 6번 — workmate-ui의 ProposalCard(app/views/Proposals.tsx)는 이 두 줄을
        보여주는데 오케스트레이터 포팅에서 빠져 있었다. 제목·날짜만으로는 무슨 내용인지,
        왜 제안됐는지 알 수 없어서 그대로 옮긴다. */}
    {typeof (proposal.metadata as Record<string, unknown> | null)?.snippet === "string" && (
      <p style={{ margin: "0 0 8px", fontSize: 12, color: "#75867f" }}>{decodeHtmlEntities(String((proposal.metadata as Record<string, unknown>).snippet))}</p>
    )}
    {typeof (proposal.metadata as Record<string, unknown> | null)?.reason === "string" && (
      <p style={{ margin: "0 0 10px", fontSize: 12, color: "#397454" }}>💡 {decodeHtmlEntities(String((proposal.metadata as Record<string, unknown>).reason))}</p>
    )}
    {result ? <p style={{ fontSize: 13, color: "#397454" }}>{result}</p> : <>
      {error && <p style={{ color: "#bd655b", fontSize: 12 }}>{error}</p>}
      {conflict && <div style={{ background: "#fff9ec", padding: 10, borderRadius: 8, marginBottom: 10 }}>
        <p style={{ margin: 0, fontSize: 12 }}>비슷한 Task가 이미 있습니다:</p>
        <ul style={{ margin: "6px 0", fontSize: 12 }}>{conflict.map((task) => <li key={task.task_id}>{task.title} (마감: {formatDateTime(task.due_at)})</li>)}</ul>
        <button type="button" disabled={busy} onClick={() => void review("approve", true)}>그래도 추가</button>
      </div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <input value={title} onChange={(event) => setTitle(event.target.value)} style={{ flex: 2, minWidth: 180, padding: "8px 10px", border: "1px solid #dfe7e1", borderRadius: 8, fontSize: 12 }} />
        <input value={assignee} onChange={(event) => setAssignee(event.target.value)} placeholder="담당자" style={{ flex: 1, minWidth: 120, padding: "8px 10px", border: "1px solid #dfe7e1", borderRadius: 8, fontSize: 12 }} />
        <input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} style={{ padding: "8px 10px", border: "1px solid #dfe7e1", borderRadius: 8, fontSize: 12 }} />
        <input type="number" min={0} max={10} value={priority} onChange={(event) => setPriority(event.target.value)} placeholder="우선순위" style={{ width: 90, padding: "8px 10px", border: "1px solid #dfe7e1", borderRadius: 8, fontSize: 12 }} />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" disabled={busy} onClick={() => void review("approve")}>승인</button>
        <button type="button" disabled={busy} onClick={() => void review("ignore")}>무시</button>
      </div>
    </>}
  </div>;
}

function MeetingSearchDetailPanel({ assigneeName }: { assigneeName: string }) {
  // 19번 문서 3단계 — `search_meetings` 실데이터로 교체(2026-08-18). 목업 질문·답변은
  // 최초 입력값으로만 남기고, 실제 제출은 백엔드 응답을 그대로 보여준다.
  const search = useSkillRunner<GroundedAnswerResult>("search_meetings", assigneeName);
  const [query, setQuery] = useState("QA 빌드 일정은 어느 회의에서 결정됐어?");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    void search.run(searchMeetingsInput(query.trim(), 5));
  }

  return <article className="meeting-search-detail">
    <span className="feature-kicker">MEETING SEARCH</span>
    <h1>이전 회의록 검색</h1>
    <p>회의에서 결정된 내용을 근거와 함께 찾아드립니다.</p>
    <form className="meeting-search-form" onSubmit={submit}>
      <input aria-label="회의록 검색어" value={query} onChange={(event) => setQuery(event.target.value)} />
      <button type="submit" disabled={search.loading}>{search.loading ? "검색 중..." : "검색"}</button>
    </form>
    {search.error && <p style={{ color: "#bd655b", marginTop: 16 }}>{search.error}</p>}
    {search.data && <section className="meeting-answer">
      <div className="answer-mark">W</div>
      <div>
        <span className="feature-kicker">WORKMATE ANSWER</span>
        <p className="answer-summary">{search.data.answer.split(/\r?\n/, 1)[0]}</p>
        {search.data.insufficient_evidence && <p className="answer-warning">근거가 충분하지 않습니다 — 참고용으로만 사용하세요.</p>}
        {!!search.data.sources.length && <>
          <div className="answer-source-heading"><strong>회의 근거</strong><span>{search.data.sources.length}건</span></div>
          <ol className="meeting-source-list">
            {search.data.sources.map((source, index) => <li key={source.meeting_chunk_id}>
              <div className="source-number">{index + 1}</div>
              <div>
                <div className="source-title"><strong>{source.meeting_title}</strong><span>{source.meeting_date}{source.speaker ? ` · ${source.speaker}` : ""}</span></div>
                <q>{source.quote}</q>
              </div>
            </li>)}
          </ol>
        </>}
        {!search.data.sources.length && <p>인용할 근거가 없습니다.</p>}
      </div>
    </section>}
  </article>;
}

function MeetingsDetailPanel({ assigneeName }: { assigneeName: string }) {
  // 19번 문서 5단계 — 회의 목록·분석·Action Item 승인 실데이터로 교체(2026-08-18).
  // `workmate-ui/app/views/Archive.tsx`의 로직을 이식하되, 스타일은 `.meeting-list`/
  // `.meeting-row` 등 이 저장소 기존 CSS를 그대로 쓴다. 범위를 좁혀 Action Item의
  // "수정"(제목·마감일 직접 편집) 폼은 이번엔 빼고 승인·거절만 이식했다 — 필요해지면
  // `workmate-ui`의 `EditForm` 패턴을 그대로 가져오면 된다.
  const config = { apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName };
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openMeetingId, setOpenMeetingId] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      setMeetings(await meetingsApi.list(config));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assigneeName]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  useEffect(() => {
    // 분석 완료 후 목록의 `has_analysis`도 별도 새로고침 없이 반영한다.
    const timer = window.setInterval(() => void load(true), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function removeMeeting(meeting: Meeting) {
    if (!window.confirm(`"${meeting.title}" 회의를 삭제할까요?`)) return;
    try {
      await meetingsApi.delete(config, meeting.meeting_id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
    }
  }

  return <article className="meetings-detail"><div className="meetings-heading"><div><span className="feature-kicker">MEETINGS</span><h1>회의 관리</h1><p>녹음, 회의록, 분석 결과를 회의별로 확인합니다.</p></div><button type="button" onClick={() => void load()}>↻ 새로고침</button></div>
    {error && <p style={{ color: "#bd655b" }}>{error}</p>}
    {loading && <p style={{ color: "#75867f" }}>불러오는 중...</p>}
    {!loading && <div className="meeting-list">
      {(meetings ?? []).map((meeting) => {
        const isOpen = openMeetingId === meeting.meeting_id;
        const date = meeting.started_at ?? meeting.created_at;
        return <div key={meeting.meeting_id}>
          <div className="meeting-row"><div className="meeting-date"><strong>{date ? String(new Date(date).getDate()).padStart(2, "0") : "-"}</strong><span>{date ? new Date(date).toLocaleString("en-US", { month: "short" }).toUpperCase() : ""}</span></div><div className="meeting-info"><strong>{meeting.title}</strong><span>{formatDateTime(date)}</span></div><b className={meeting.has_analysis ? "analysis-done" : "analysis-waiting"}>{meeting.has_analysis ? "분석 완료" : "분석 대기"}</b><button type="button" aria-label={`${meeting.title} 삭제`} style={{ fontSize: 11 }} onClick={() => void removeMeeting(meeting)}>삭제</button><button type="button" className="meeting-arrow" aria-label={`${meeting.title} 열기`} onClick={() => setOpenMeetingId(isOpen ? null : meeting.meeting_id)}>{isOpen ? "↓" : "⟶"}</button></div>
          {isOpen && <MeetingDetailSection meeting={meeting} assigneeName={assigneeName} onFreshAnalysis={load} />}
        </div>;
      })}
      {!meetings?.length && <p style={{ color: "#75867f" }}>등록된 회의가 없습니다. &lsquo;회의 녹음&rsquo; 화면에서 회의를 만들어보세요.</p>}
    </div>}
  </article>;
}

type MeetingDetailProps = { meeting: Meeting; assigneeName: string; onFreshAnalysis: () => void };

function MeetingDetailSection({ meeting, assigneeName, onFreshAnalysis }: MeetingDetailProps) {
  const config = { apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName };
  const fetchAnalysis = useCallback(() => meetingsApi.getAnalysis(config, meeting.meeting_id), [assigneeName, meeting.meeting_id]);
  const analysis = usePollingSkillRunner<MeetingAnalysisResult>("analyze_meeting", assigneeName, fetchAnalysis);
  // 이미 저장된 분석 결과 — 회의를 펼칠 때마다 `analyze_meeting`(느린 STT+LLM)을
  // 다시 돌리지 않고, 저장된 값이 있으면 그걸 먼저 보여준다.
  const [existing, setExisting] = useState<MeetingAnalysisResult | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Partial<ActionItem>>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const loadExisting = async () => {
      try {
        const result = await fetchAnalysis();
        if (!cancelled) {
          setExisting(result);
          if (timer !== undefined) window.clearInterval(timer);
        }
      } catch {
        // 분석 결과가 저장되는 시점이 Task 완료와 다를 수 있어 재시도한다.
      }
    };
    void loadExisting();
    if (meeting.has_analysis) timer = window.setInterval(() => void loadExisting(), 2000);
    return () => { cancelled = true; if (timer !== undefined) window.clearInterval(timer); };
    // meeting.has_analysis가 false→true로 바뀌는 순간(목록 폴링으로 갱신됨) 다시 실행해
    // 폴링을 시작해야 한다. 그렇지 않으면 상세 패널이 "불러오는 중"에 멈춰 있게 된다.
  }, [fetchAnalysis, meeting.has_analysis]);

  const data = analysis.data ?? existing;
  const items: ActionItem[] = (data?.action_items ?? []).map((item) => ({ ...item, ...overrides[item.action_item_id] }));
  const pendingCount = items.filter((item) => item.approval_status === "pending").length;

  async function runAnalysis() {
    const result = await analysis.run(analyzeMeetingInput(meeting.meeting_id));
    if (result) onFreshAnalysis();
  }

  function applyResults(results: { action_item_id: string; approval_status: string }[]) {
    setOverrides((prev) => {
      const next = { ...prev };
      for (const result of results) next[result.action_item_id] = { ...next[result.action_item_id], approval_status: result.approval_status as ActionItem["approval_status"] };
      return next;
    });
  }

  async function review(actionItemId: string, decision: "approve" | "reject") {
    setBusyId(actionItemId);
    try {
      const { results } = await meetingsApi.reviewActions(config, meeting.meeting_id, [{ action_item_id: actionItemId, decision }]);
      applyResults(results);
    } catch {
      // 실패는 버튼이 다시 활성화되는 것으로 드러난다.
    } finally {
      setBusyId(null);
    }
  }

  async function approveAllPending() {
    const pending = items.filter((item) => item.approval_status === "pending");
    if (!pending.length) return;
    setBusyId("__all__");
    try {
      const { results } = await meetingsApi.reviewActions(config, meeting.meeting_id, pending.map((item) => ({ action_item_id: item.action_item_id, decision: "approve" as const })));
      applyResults(results);
    } finally {
      setBusyId(null);
    }
  }

  return <div style={{ borderTop: "1px solid #e6ece7", marginTop: 8, paddingTop: 12 }}>
    <TranscriptSection meetingId={meeting.meeting_id} assigneeName={assigneeName} />
    {!data && meeting.has_analysis && <p style={{ color: "#75867f" }}>분석 결과를 불러오는 중...</p>}
    {!data && !meeting.has_analysis && <button type="button" disabled={analysis.loading} onClick={() => void runAnalysis()}>{analysis.loading ? "분석 중... (완료될 때까지 상태를 확인합니다)" : "회의 분석 실행 (analyze_meeting)"}</button>}
    {analysis.error && <p style={{ color: "#bd655b" }}>{analysis.error}</p>}
    {data && <>
      <h3 style={{ marginTop: 0 }}>요약</h3>
      <p style={{ fontSize: 13, color: "#34594a" }}>{data.summary}</p>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Action Item {items.length}건</h3>
        {pendingCount > 1 && <button type="button" style={{ marginLeft: "auto", fontSize: 11 }} disabled={busyId !== null} onClick={() => void approveAllPending()}>대기 {pendingCount}건 일괄 승인</button>}
      </div>
      {items.map((action) => {
        const isApproved = action.approval_status === "approved";
        const isRejected = action.approval_status === "rejected";
        const isPending = action.approval_status === "pending";
        const isBusy = busyId === action.action_item_id || busyId === "__all__";
        return <div key={action.action_item_id} style={{ borderTop: "1px solid #edf1ed", padding: "10px 0" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <b style={{ fontSize: 13 }}>{action.title}</b>
            <span className={`analysis ${isApproved ? "done" : "pending"}`}>{isApproved ? "승인됨" : isRejected ? "거절됨" : "대기"}</span>
            {isPending && <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}><button type="button" style={{ fontSize: 11 }} disabled={isBusy} onClick={() => void review(action.action_item_id, "reject")}>거절</button><button type="button" style={{ fontSize: 11 }} disabled={isBusy} onClick={() => void review(action.action_item_id, "approve")}>승인</button></div>}
          </div>
          {action.description && <p style={{ margin: "4px 0 0", color: "#75867f", fontSize: 12 }}>{action.description}</p>}
          {action.due_at && <p style={{ margin: "4px 0 0", color: "#75867f", fontSize: 12 }}>마감: {formatDateTime(action.due_at)}</p>}
          <p style={{ margin: "6px 0 0", color: "#75867f", fontSize: 12 }}>{action.evidence_text}</p>
        </div>;
      })}
      {!items.length && <p style={{ color: "#75867f" }}>추출된 Action Item이 없습니다.</p>}
    </>}
  </div>;
}

// 업로드·녹음 직후엔 최종 Transcript가 아직 없다 — 파일 기반 STT는 `analyze_meeting`을
// 처음 실행할 때 회의 전체 원본 음성에서 자동으로 수행된다. 그래서 이 영역은 분석
// 여부와 무관하게 항상 보이되, 없을 때는 이유를 그대로 안내한다.
function TranscriptSection({ meetingId, assigneeName }: { meetingId: string; assigneeName: string }) {
  const [expanded, setExpanded] = useState(false);
  const [rows, setRows] = useState<TranscriptRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setRows(await meetingsApi.transcript({ apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName }, meetingId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    const next = !expanded;
    setExpanded(next);
    if (next && rows === null) void load();
  }

  // 실시간 자막 Streaming은 아직 연결되지 않아(is_final=0) 임시 Chunk는 항상 빈
  // 문자열이다 — 최종(is_final=1) Row만 원문으로 표시한다.
  const finalRows = (rows ?? []).filter((row) => row.is_final === 1).sort((a, b) => a.chunk_no - b.chunk_no);

  return <div style={{ marginBottom: 10 }}>
    <button type="button" onClick={toggle}>{expanded ? "전체 스크립트 접기" : "전체 스크립트 보기"}</button>
    {expanded && <div style={{ marginTop: 8, padding: 12, background: "#fbfcfb", border: "1px solid #e6ece7", borderRadius: 8 }}>
      {loading && <p style={{ color: "#75867f" }}>불러오는 중...</p>}
      {error && <p style={{ color: "#bd655b" }}>{error}</p>}
      {!loading && !error && rows !== null && finalRows.length === 0 && <p style={{ color: "#75867f" }}>아직 최종 스크립트가 없습니다. 회의 분석을 실행하면 원본 음성을 텍스트로 자동 변환합니다.</p>}
      {finalRows.map((row) => <p key={row.transcript_id} style={{ fontSize: 13, margin: "6px 0" }}>{row.text}</p>)}
    </div>}
  </div>;
}

function defaultMeetingTitle(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `회의 ${now.getMonth() + 1}월 ${now.getDate()}일 ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

type CaptionEvent = { chunkNo: number; text: string; at: string };

function RecordingDetailPanel({ assigneeName, onRecordingChange }: { assigneeName: string; onRecordingChange: (recording: boolean) => void }) {
  // 19번 문서 6단계 — 회의 생성·업로드(REST)는 결정 5의 담당자 헤더로, 실시간
  // WebSocket(`recording-stream`)은 별도 신원 경로다(`recording_stream.py`의
  // `_credentials`는 REST의 `_authenticated_user_or_assignee`를 거치지 않고
  // `Sec-WebSocket-Protocol`만 본다) — `resolveAssigneeUserId`로 미리 계산해 둔
  // 고정 `user_id`를 그대로 `user.<id>` Subprotocol에 실어 보낸다.
  const [recordTitle, setRecordTitle] = useState(defaultMeetingTitle());
  const [recording, setRecording] = useState(false);
  const [paused, setPaused] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [captions, setCaptions] = useState<CaptionEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadTitle, setUploadTitle] = useState(defaultMeetingTitle());
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunkNoRef = useRef(0);
  const meetingIdRef = useRef<string | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorNodeRef = useRef<ScriptProcessorNode | null>(null);
  const chunkBufferRef = useRef(new Pcm16ChunkBuffer());
  const uploadInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // 언마운트(=다른 탭으로 이동, 결정 4) 시 마이크·WebSocket을 정리한다 —
    // 정리 자체가 서버 쪽 "연결 끊김 = 세션 확정"을 트리거한다(의도된 동작).
    return () => {
      socketRef.current?.close(1000);
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function startRecording() {
    setError(null);
    const config = { apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName };
    const resolvedUserId = resolveAssigneeUserId(assigneeName);
    if (!resolvedUserId) {
      setError("이 담당자로는 실시간 녹음을 시작할 수 없습니다 — 담당자 설정을 확인하세요.");
      return;
    }
    try {
      const meeting = await meetingsApi.create(config, { title: recordTitle.trim() || defaultMeetingTitle(), meeting_id: crypto.randomUUID() });
      meetingIdRef.current = meeting.meeting_id;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `회의 생성 실패: ${(err as Error).message}`);
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError(`마이크 접근 실패: ${(err as Error).message}`);
      return;
    }
    streamRef.current = stream;

    const meetingId = meetingIdRef.current;
    const wsUrl = `${WORKMATE_API_BASE_URL.replace(/^http/, "ws")}/api/v1/meetings/${encodeURIComponent(meetingId!)}/recording-stream`;
    const socket = new WebSocket(wsUrl, [`bearer.assignee-auth`, `user.${encodeURIComponent(resolvedUserId)}`]);
    socketRef.current = socket;
    chunkNoRef.current = 0;
    chunkBufferRef.current = new Pcm16ChunkBuffer();
    setCaptions([]);
    setPaused(false);

    socket.addEventListener("open", () => { setRecording(true); onRecordingChange(true); });
    socket.addEventListener("close", () => { setRecording(false); setProcessing(false); onRecordingChange(false); });
    socket.addEventListener("error", () => setError("WebSocket 연결 오류가 발생했습니다."));
    socket.addEventListener("message", (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "transcript.partial") {
        setCaptions((prev) => {
          const entry = { chunkNo: payload.chunk_no, text: payload.text, at: new Date().toLocaleTimeString("ko-KR") };
          const index = prev.findIndex((caption) => caption.chunkNo === payload.chunk_no);
          const next = index >= 0 ? prev.map((caption, i) => (i === index ? entry : caption)) : [...prev, entry];
          return next.slice(-20);
        });
      }
    });

    const audioContext = new AudioContext();
    audioContextRef.current = audioContext;
    const source = audioContext.createMediaStreamSource(stream);
    sourceNodeRef.current = source;
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    processorNodeRef.current = processor;
    processor.onaudioprocess = (event) => {
      if (socket.readyState !== WebSocket.OPEN) return;
      const input = event.inputBuffer.getChannelData(0);
      const resampled = resampleLinear(input, audioContext.sampleRate, STT_SAMPLE_RATE);
      const pcm16 = float32ToPcm16(resampled);
      for (const chunk of chunkBufferRef.current.push(pcm16)) {
        socket.send(JSON.stringify({ chunk_no: chunkNoRef.current, audio_base64: pcm16ToBase64(chunk) }));
        chunkNoRef.current += 1;
      }
    };
    const silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(audioContext.destination);
  }

  function togglePause() {
    const audioContext = audioContextRef.current;
    if (!audioContext) return;
    if (paused) {
      void audioContext.resume();
      setPaused(false);
    } else {
      void audioContext.suspend();
      setPaused(true);
    }
  }

  function stopRecording() {
    processorNodeRef.current?.disconnect();
    sourceNodeRef.current?.disconnect();
    void audioContextRef.current?.close();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    const remainder = chunkBufferRef.current.flush();
    if (remainder && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ chunk_no: chunkNoRef.current, audio_base64: pcm16ToBase64(remainder) }));
      chunkNoRef.current += 1;
    }
    setProcessing(true);
    socketRef.current?.close(1000);
    processorNodeRef.current = null;
    sourceNodeRef.current = null;
    audioContextRef.current = null;
    streamRef.current = null;
    socketRef.current = null;
    setRecording(false);
    setPaused(false);
  }

  async function handleUpload(file: File) {
    setError(null);
    setUploading(true);
    setUploadStatus(null);
    const config = { apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName };
    try {
      const meeting = await meetingsApi.create(config, { title: uploadTitle.trim() || defaultMeetingTitle(), meeting_id: crypto.randomUUID() });
      const uploaded = await meetingsApi.uploadRecording(config, meeting.meeting_id, file);
      setUploadStatus(`업로드 완료: ${uploaded.filename} (${(uploaded.size_bytes / 1024).toFixed(1)}KB) · 회의 관리에서 분석을 실행하세요.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `업로드 실패: ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  }

  return <article className="recording-detail"><span className="feature-kicker">NEW MEETING</span><h1>회의 녹음 및 분석</h1><p>실시간으로 녹음하거나 기존 파일을 업로드하세요.</p>
    {error && <p style={{ color: "#bd655b", marginTop: 12 }}>{error}</p>}
    <div className="recording-options">
      <section>
        <div className="recording-icon live">{processing ? "…" : recording ? "■" : "●"}</div>
        <h2>{processing ? "처리 중" : recording ? (paused ? "일시정지됨" : "녹음 중") : "실시간 녹음"}</h2>
        {!recording && !processing && <input value={recordTitle} onChange={(event) => setRecordTitle(event.target.value)} placeholder="회의 제목" style={{ margin: "10px 0", width: "100%", padding: "8px 10px", border: "1px solid #dfe7e1", borderRadius: 8, fontSize: 12, textAlign: "center" }} />}
        <p>{processing ? "녹음을 원본 음성으로 저장하는 중입니다." : recording ? (paused ? "일시정지됨 — 재개를 누르면 이어서 전송합니다." : "마이크 오디오를 200ms 간격으로 전송하고 있습니다.") : "마이크 음성을 실시간으로 전송합니다."}</p>
        <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
          {recording && <button type="button" onClick={togglePause}>{paused ? "재개" : "일시정지"}</button>}
          <button type="button" onClick={recording ? stopRecording : () => void startRecording()} disabled={processing}>{processing ? "처리 중..." : recording ? "녹음 종료" : "녹음 시작"}</button>
        </div>
      </section>
      <section>
        <div className="recording-icon upload">⇧</div>
        <h2>녹음 파일 업로드</h2>
        <input value={uploadTitle} onChange={(event) => setUploadTitle(event.target.value)} placeholder="회의 제목" style={{ margin: "10px 0", width: "100%", padding: "8px 10px", border: "1px solid #dfe7e1", borderRadius: 8, fontSize: 12, textAlign: "center" }} />
        <p>MP3, WAV, M4A, WebM, OGG · 최대 500MB</p>
        <input ref={uploadInputRef} type="file" hidden accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/webm,audio/ogg,.mp3,.wav,.m4a" onChange={(event) => { const file = event.target.files?.[0]; if (file) void handleUpload(file); event.target.value = ""; }} />
        <button type="button" onClick={() => uploadInputRef.current?.click()} disabled={uploading}>{uploading ? "업로드 중..." : "파일 선택"}</button>
        {uploadStatus && <p style={{ marginTop: 10, color: "#75867f", fontSize: 12 }}>{uploadStatus}</p>}
      </section>
    </div>
    {recording && <section style={{ marginTop: 18, padding: 16, background: "#fff", border: "1px solid #dfe7e1", borderRadius: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><h2 style={{ margin: 0, fontSize: 15 }}>실시간 자막</h2><span style={{ color: "#bd655b", fontSize: 11, fontWeight: 800 }}>LIVE</span></div>
      {captions.map((caption) => <p key={caption.chunkNo} style={{ fontSize: 12, margin: "6px 0", color: "#34594a" }}><time style={{ color: "#75867f", marginRight: 6 }}>{caption.at}</time><b style={{ marginRight: 6 }}>chunk #{caption.chunkNo}</b>{caption.text || "(자막 텍스트 없음)"}</p>)}
      {!captions.length && <p style={{ color: "#75867f", fontSize: 12 }}>Chunk ACK를 기다리는 중...</p>}
    </section>}
  </article>;
}

type TaskFilterKey = "all" | "in_progress" | "blocked";
const TASK_FILTER_STATUS: Record<TaskFilterKey, TaskStatus | null> = { all: null, in_progress: "in_progress", blocked: "blocked" };
const TASK_STATUS_OPTIONS: TaskStatus[] = ["todo", "in_progress", "blocked", "done", "cancelled"];
// `.task-status`의 기존 CSS는 progress/delayed/todo 3가지 색만 정의한다(오늘 브리핑과 같은
// 목업 시절부터 있던 배지) — done·cancelled는 todo와 같은 회색 배지를 그대로 쓴다.
const TASK_STATUS_CSS_CLASS: Record<TaskStatus, string> = { todo: "todo", in_progress: "progress", blocked: "delayed", done: "todo", cancelled: "todo" };

function TaskDetailPanel({ assigneeName }: { assigneeName: string }) {
  // 19번 문서 4단계 — `/api/v1/tasks` CRUD 실데이터로 교체(2026-08-18). 원래 목업엔
  // "담당자" 컬럼이 있었지만 Workmate MVP엔 그 개념이 없어(15번 문서 "담당자 필드는
  // 만들지 않는다") `workmate-ui/app/views/Tasks.tsx`와 동일하게 뺐다 — 대신 그 자리에
  // 수정·완료·삭제 액션을 넣는다.
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<TaskFilterKey>("all");
  const [query, setQuery] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [priorityHint, setPriorityHint] = useState("");
  const [status, setStatus] = useState<TaskStatus>("todo");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const statusFilter = TASK_FILTER_STATUS[filter];
      setTasks(await tasksApi.list({ apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName }, { status: statusFilter ?? undefined }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [assigneeName, filter]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const counts = useMemo(() => summarizeTaskCounts(tasks ?? []), [tasks]);
  const visible = useMemo(() => (tasks ?? []).filter((task) => matchesQuery(task.title, query)), [tasks, query]);

  function openCreateForm() {
    setEditingTaskId(null);
    setTitle("");
    setDueAt("");
    setPriorityHint("");
    setStatus("todo");
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingTaskId(null);
  }

  async function submitForm(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    const priorityValue = priorityHint.trim() === "" ? null : Number(priorityHint);
    const config = { apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName };
    try {
      if (editingTaskId) {
        await tasksApi.update(config, editingTaskId, { title: title.trim(), due_at: dueAt ? new Date(dueAt).toISOString() : null, priority_hint: priorityValue, status });
      } else {
        await tasksApi.create(config, { title: title.trim(), due_at: dueAt ? new Date(dueAt).toISOString() : null, priority_hint: priorityValue });
      }
      closeForm();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
    }
  }

  async function removeTask(task: Task) {
    if (!window.confirm(`"${task.title}"을(를) 삭제할까요?`)) return;
    try {
      await tasksApi.remove({ apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName }, task.task_id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
    }
  }

  async function toggleDone(task: Task) {
    try {
      await tasksApi.update({ apiBase: WORKMATE_API_BASE_URL, assignee: assigneeName }, task.task_id, { status: task.status === "done" ? "todo" : "done" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `예상치 못한 오류: ${(err as Error).message}`);
    }
  }

  return <article className="task-detail-panel"><div className="task-detail-heading"><div><span className="feature-kicker">TASKS</span><h1>할 일 관리</h1><p>직접 등록하거나 메일·일정·회의에서 승인한 업무입니다.</p></div><button type="button" onClick={() => (showForm && !editingTaskId ? closeForm() : openCreateForm())}>＋ 할 일 등록</button></div>
    {showForm && <form onSubmit={submitForm} style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", padding: "14px 22px", borderBottom: "1px solid #e6ece7" }}>
      <label style={{ flex: 1, minWidth: 200, fontSize: 12, color: "#75867f" }}>제목<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="예: 주간 보고서 작성" style={{ width: "100%", marginTop: 6, padding: "9px 11px", border: "1px solid #dfe7e1", borderRadius: 8 }} /></label>
      <label style={{ fontSize: 12, color: "#75867f" }}>마감일<input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} style={{ display: "block", marginTop: 6, padding: "9px 11px", border: "1px solid #dfe7e1", borderRadius: 8 }} /></label>
      <label style={{ fontSize: 12, color: "#75867f" }}>중요도<input type="number" min={0} max={10} value={priorityHint} onChange={(event) => setPriorityHint(event.target.value)} placeholder="0~10" style={{ display: "block", marginTop: 6, padding: "9px 11px", border: "1px solid #dfe7e1", borderRadius: 8, width: 80 }} /></label>
      {editingTaskId && <label style={{ fontSize: 12, color: "#75867f" }}>상태<select value={status} onChange={(event) => setStatus(event.target.value as TaskStatus)} style={{ display: "block", marginTop: 6, padding: "9px 11px", border: "1px solid #dfe7e1", borderRadius: 8 }}>{TASK_STATUS_OPTIONS.map((value) => <option key={value} value={value}>{taskStatusBadge(value)}</option>)}</select></label>}
      <button type="submit">{editingTaskId ? "수정 저장" : "등록"}</button>
      <button type="button" onClick={closeForm}>취소</button>
    </form>}
    {error && <p style={{ color: "#bd655b", padding: "0 22px" }}>{error}</p>}
    <div className="task-toolbar"><div className="task-filters"><button className={filter === "all" ? "active" : ""} type="button" onClick={() => setFilter("all")}>전체 {tasks?.length ?? "-"}</button><button className={filter === "in_progress" ? "active" : ""} type="button" onClick={() => setFilter("in_progress")}>진행 중 {counts.in_progress}</button><button className={filter === "blocked" ? "active" : ""} type="button" onClick={() => setFilter("blocked")}>지연 {counts.blocked}</button></div><input aria-label="할 일 검색" placeholder="할 일 검색" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
    {loading && <p style={{ padding: 20, color: "#75867f" }}>불러오는 중...</p>}
    {!loading && <div className="task-table"><div className="task-table-head"><span>할 일</span><span>마감</span><span>상태</span><span>중요도</span><span></span></div>
      {visible.map((task) => <div className="task-table-row" key={task.task_id}><span>{task.title}</span><span>{task.due_at ? new Date(task.due_at).toLocaleDateString("ko-KR") : "-"}</span><span><b className={`task-status ${TASK_STATUS_CSS_CLASS[task.status]}`}>{taskStatusBadge(task.status)}</b></span><span>{task.priority_hint ?? "-"}</span><span style={{ display: "flex", gap: 6, flexWrap: "nowrap" }}><button type="button" style={{ padding: "6px 8px", fontSize: 11, whiteSpace: "nowrap" }} onClick={() => { setEditingTaskId(task.task_id); setTitle(task.title); setDueAt(task.due_at ?? ""); setPriorityHint(task.priority_hint === null ? "" : String(task.priority_hint)); setStatus(task.status); setShowForm(true); }}>수정</button><button type="button" style={{ padding: "6px 8px", fontSize: 11, whiteSpace: "nowrap" }} onClick={() => toggleDone(task)}>{task.status === "done" ? "되돌리기" : "완료"}</button><button type="button" style={{ padding: "6px 8px", fontSize: 11, whiteSpace: "nowrap" }} onClick={() => removeTask(task)}>삭제</button></span></div>)}
      {!visible.length && <p style={{ padding: 20, color: "#75867f" }}>조건에 맞는 할 일이 없습니다.</p>}
    </div>}
  </article>;
}

// 22번 문서 — 오늘 브리핑(`daily_briefing`+`rank_priorities`)·주간 업무보고(`weekly_report`)를
// `workmate-ui` 원본(`app/views/Briefing.tsx`/`Report.tsx`)과 필드 단위로 대조해 다시 실데이터로
// 이식했다(2026-08-19). 19번 문서 3단계 때는 이 화면들을 이미 한 번 이식했다가 목업으로
// 롤백됐었는데, 그 구현이 원본에 있던 세 가지를 빠뜨리고 있었다 — 이번엔 그 세 가지를 포함한다.
// 1) Provider(Gmail/Calendar/Task/Meeting) 실패 시 부분 결과 + 경고 배너(`SkillWarningsBanner`),
// 2) 그 경고를 반영한 소스 상태 표시(`.signal-strip`을 하드코딩에서 동적으로),
// 3) 우선순위 카드의 배점 내역(`score_breakdown`).
const SOURCE_LABELS: Record<string, string> = { task: "Task", calendar: "Calendar", email: "Gmail", meeting: "Meeting" };

const SCORE_BREAKDOWN_LABELS: Record<keyof PriorityScoreBreakdown, string> = {
  deadline: "마감임박도",
  importance: "중요도",
  blocked_or_overdue: "지연/차단",
  meeting_commitment: "회의 약속",
  calendar_relevance: "일정 연관",
};

// 새 CSS 클래스를 늘리지 않고, 화면이 이미 에러 표시에 쓰던 색 톤(`#bd655b` 계열)을 인라인
// 스타일로 재사용한다(`workmate-ui/app/views/shared.tsx::WarningsList`에 대응).
function SkillWarningsBanner({ warnings }: { warnings: SkillWarning[] }) {
  if (!warnings.length) return null;
  return <div style={{ margin: "0 auto 16px", maxWidth: 1040, padding: "12px 16px", border: "1px solid #f0c2bd", background: "#fdf1f0", borderRadius: 10, color: "#8a3f37", fontSize: 12 }}>
    {warnings.map((warning, index) => <p key={`${warning.code}-${index}`} style={{ margin: index === 0 ? 0 : "6px 0 0" }}><b>{warning.source}</b>: {warning.message}{warning.retryable ? " (재시도 가능)" : ""}</p>)}
  </div>;
}

export function ReferenceBriefingPanel({ kind, assigneeName = "병준", onConfirm }: { kind: "briefing" | "weekly"; assigneeName?: string; onConfirm?: () => void }) {
  const weekly = kind === "weekly";
  // `kind="weekly"` 경로는 실제로 호출되지 않는다(App.tsx는 주간 업무보고에
  // `WeeklyReportPanel`을 따로 쓴다) — 그 경로는 기존 목업 그대로 남겨 둔다.
  const briefing = useSkillRunner<DailyBriefingResult>("daily_briefing", assigneeName);
  const priorities = useSkillRunner<PriorityRankingResult>("rank_priorities", assigneeName);

  const load = useCallback(() => {
    void briefing.run(dailyBriefingInput());
    void priorities.run(rankPrioritiesInput());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assigneeName]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!weekly) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weekly, assigneeName]);

  if (weekly) {
    return <section className="report-panel report-dashboard"><div className="briefing-header"><div><span className="briefing-date">2026년 8월 7일 금요일</span><h1>이번 주 업무 보고</h1><p>이번 주 업무 진행 상황과 다음 주 계획을 한눈에 확인하세요.</p></div><button className="refresh-report" type="button">↻ 새로고침</button></div><div className="signal-strip"><span>● Task 최신</span><span>● Calendar 1분 전</span><span>● Gmail 일부 지연</span><span>● Meeting 최신</span></div><div className="briefing-section-title"><span>FOCUS</span><h2>이번 주 우선순위 Top 3</h2><small>09:02 계산</small></div><div className="priority-grid"><article className="priority-card featured"><b>1</b><strong>QA 서버 빌드 배포</strong><span>이번 주 완료 · 개발팀</span><em>85점</em><hr/><small>오늘 마감 · 중요도 높음 · 15시 QA 회의</small></article><article className="priority-card"><b>2</b><strong>로그인 오류 원인 분석</strong><span>1일 지연 · 클라이언트팀</span><em>78점</em><hr/><small>기한 초과 · 다른 업무 차단</small></article><article className="priority-card"><b>3</b><strong>신규 캐릭터 밸런스 검토</strong><span>내일 12:00 · 기획팀</span><em>64점</em><hr/><small>회의 Action Item · 내일 마감</small></article></div><div className="briefing-columns"><section className="briefing-list"><h2>이번 주 주요 업무 <small>4건</small></h2><div><b>월</b><strong>데일리 스크럼</strong><span>개발팀 · 30분</span></div><div><b>수</b><strong>QA 빌드 검토</strong><span>QA팀 · 1시간</span></div><div><b>금</b><strong>캐릭터 기획 리뷰</strong><span>기획팀 · 1시간</span></div></section><section className="briefing-list"><h2>중요 업무 신호 <small>2개</small></h2><div><b className="signal-red">M</b><strong>[QA] 빌드 배포 일정 확인 요청</strong><span>마감일이 포함된 할 일 후보입니다.</span><a>할 일 추가</a></div><div><b className="signal-blue">C</b><strong>스토어 심사 제출</strong><span>아직 할 일로 등록되지 않은 일정입니다.</span><a>할 일 추가</a></div></section></div></section>;
  }

  if (briefing.loading || priorities.loading) return <section className="report-panel report-dashboard" style={{ textAlign: "center", padding: "60px 20px", color: "#75867f" }}>오늘 브리핑을 불러오는 중...</section>;
  if (briefing.error) return <section className="report-panel report-dashboard" style={{ padding: "40px 20px", color: "#bd655b" }}>{briefing.error}</section>;
  if (priorities.error) return <section className="report-panel report-dashboard" style={{ padding: "40px 20px", color: "#bd655b" }}>{priorities.error}</section>;
  if (!briefing.data) return <section className="report-panel report-dashboard" style={{ textAlign: "center", padding: "60px 20px", color: "#75867f" }}>브리핑을 아직 실행하지 않았습니다.</section>;

  const data = briefing.data;
  const top3 = (priorities.data?.priorities ?? []).slice(0, 3);
  // Provider별(Task/Calendar/Gmail/Meeting) 경고를 두 Skill 호출에서 합쳐, `.signal-strip`의
  // "최신"/"지연" 표시와 경고 배너 둘 다 이 하나의 집합으로 계산한다(원본 `Briefing.tsx`와 동일).
  const warnings = [...briefing.warnings, ...priorities.warnings];
  const degradedSources = new Set(warnings.map((warning) => warning.source));

  return <section className="report-panel report-dashboard"><div className="briefing-header"><div><span className="briefing-date">{formatKoreanDate(data.date)}</span><h1>좋은 아침이에요, {assigneeName}님.</h1><p>{data.summary}</p></div><button className="refresh-report" type="button" onClick={load}>↻ 새로고침</button></div><div className="signal-strip">{Object.entries(SOURCE_LABELS).map(([key, label]) => <span key={key}>● {label} {degradedSources.has(key) ? "지연" : "최신"}</span>)}</div><SkillWarningsBanner warnings={warnings} /><div className="briefing-section-title"><span>FOCUS</span><h2>오늘의 우선순위 Top 3</h2><small>{priorities.data ? new Date(priorities.data.calculated_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : ""} 계산</small></div><div className="priority-grid">{top3.map((item, index) => { const change = priorities.data?.changes.find((c) => c.task_id === item.task_id); const movement = change ? movementLabel(change.change_type, change.previous_rank, change.current_rank) : null; return <article className={`priority-card${index === 0 ? " featured" : ""}`} key={item.task_id}><b>{item.rank}</b><strong>{item.title}</strong><span>{item.reasons.join(" · ")}</span><em>{item.score}점</em><hr/><small>{movement ?? change?.reason ?? ""}</small>{item.score_breakdown && <small>{(Object.keys(SCORE_BREAKDOWN_LABELS) as (keyof PriorityScoreBreakdown)[]).map((key) => `${SCORE_BREAKDOWN_LABELS[key]} ${item.score_breakdown![key]}`).join(" · ")}</small>}</article>; })}{!top3.length && <p style={{ gridColumn: "1 / -1", color: "#75867f" }}>계산된 우선순위가 없습니다.</p>}</div><div className="briefing-columns"><section className="briefing-list"><h2>오늘 일정 <small>{data.calendar_events.length}개</small></h2>{data.calendar_events.map((event) => <div key={event.event_id}><b>{new Date(event.starts_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</b><strong>{event.title}</strong>{event.related_task_ids && event.related_task_ids.length > 0 && <span>등록됨</span>}</div>)}{!data.calendar_events.length && <p style={{ color: "#75867f" }}>오늘 일정이 없습니다.</p>}</section><section className="briefing-list"><h2>중요 업무 신호 <small>{data.important_signals.length}개</small></h2>{data.important_signals.map((signal) => <div key={signal.source_id}><b className={signal.type === "email" ? "signal-red" : "signal-blue"}>{signal.type === "email" ? "M" : "C"}</b><strong>{truncateText(decodeHtmlEntities(signal.summary), 140)}</strong>{signal.related_task_ids && signal.related_task_ids.length > 0 && <span>등록됨</span>}</div>)}{!data.important_signals.length && <p style={{ color: "#75867f" }}>중요 신호가 없습니다.</p>}</section></div></section>;
}

export function WeeklyReportPanel({ assigneeName = "병준", onConfirm }: { assigneeName?: string; onConfirm?: () => void }) {
  const report = useSkillRunner<WeeklyReportResult>("weekly_report", assigneeName);
  const [markdown, setMarkdown] = useState("");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const [defaultWeekOf] = useState(() => defaultWeeklyReportWeekOf());
  const [weekOf, setWeekOf] = useState(defaultWeekOf);

  const load = useCallback(
    async (targetWeekOf: string) => {
      const response = await report.run(weeklyReportInput(targetWeekOf));
      setMarkdown(response?.artifact.markdown ?? "");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [assigneeName],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(weekOf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weekOf, assigneeName]);

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
    setTimeout(() => setCopyStatus("idle"), 1500);
  }

  if (report.loading) return <section className="report-panel weekly-dashboard" style={{ textAlign: "center", padding: "60px 20px", color: "#75867f" }}>주간 보고서를 생성하는 중...</section>;
  if (report.error) return <section className="report-panel weekly-dashboard" style={{ padding: "40px 20px", color: "#bd655b" }}>{report.error}</section>;
  if (!report.data) return <section className="report-panel weekly-dashboard" style={{ textAlign: "center", padding: "60px 20px", color: "#75867f" }}>아직 보고서를 생성하지 않았습니다.</section>;

  const data = report.data;

  return <section className="report-panel weekly-dashboard"><div className="weekly-header">
    {/* LLM 요약 문단(data.summary)은 길이가 매번 달라진다 — min-width:0이 없으면 flex 항목은
        기본적으로 자기 내용 크기 밑으로 잘 줄어들지 않아, 오른쪽 버튼 그룹과 폭을 다투다 버튼
        쪽이 비정상적으로 짜부러진다(workmate-ui `app/views/Report.tsx`와 같은 수정). */}
    <div style={{ minWidth: 0 }}><span>{formatKoreanDate(data.period.start)} — {formatKoreanDate(data.period.end)}</span><h1>주간 업무보고</h1><p>{data.summary}</p></div>
    {/* flexShrink:0 + 버튼별 whiteSpace:nowrap — 왼쪽 요약 문단이 길어져도 이 버튼 그룹은
        줄어들지 않는다. 이게 없으면 좁아진 버튼 안에서 "이전 주" 같은 한글 두 글자가 음절
        단위로 세로 줄바꿈돼 버튼이 세로로 길게 늘어나 보였다(2026-08-19 실사용 중 발견). */}
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
      <button type="button" style={{ whiteSpace: "nowrap" }} onClick={() => setWeekOf(shiftIsoDate(data.period.start, -7))}>◀ 이전 주</button>
      {weekOf !== defaultWeekOf && <button type="button" style={{ whiteSpace: "nowrap" }} onClick={() => setWeekOf(defaultWeekOf)}>최근 1주로</button>}
      <button type="button" style={{ whiteSpace: "nowrap" }} onClick={() => setWeekOf(shiftIsoDate(data.period.start, 7))}>다음 주 ▶</button>
      <button type="button" style={{ whiteSpace: "nowrap" }} onClick={copyMarkdown} disabled={!markdown}>{copyStatus === "copied" ? "복사됨!" : copyStatus === "failed" ? "복사 실패" : "Markdown 복사"}</button>
    </div>
  </div><SkillWarningsBanner warnings={report.warnings} /><div className="weekly-metrics"><article><strong>{data.completed.length}</strong><span>완료 업무</span></article><article><strong>{data.in_progress.length}</strong><span>진행 중</span></article><article className="delayed"><strong>{data.delayed.length}</strong><span>지연 업무</span></article><article><strong>{data.unresolved_issues.length}</strong><span>미해결 이슈</span></article></div><div className="weekly-report-grid"><WeeklyReportBlock title="완료 업무" items={data.completed} /><WeeklyReportBlock title="진행 중 업무" items={data.in_progress} /><WeeklyReportBlock title="지연 업무" items={data.delayed} /><WeeklyReportBlock title="미해결 이슈" items={data.unresolved_issues} /><WeeklyPlanBlock title="다음 주 계획" items={data.next_week_plans} /></div></section>;
}

function WeeklyReportBlock({ title, items }: { title: string; items: WorkItem[] }) {
  return <section><h2>{title}</h2>{items.length ? items.map((item) => <p key={item.task_id}>✓ {item.title}{item.summary ? ` — ${item.summary}` : ""}</p>) : <p>없음</p>}</section>;
}

// 근거 없이 LLM이 만들어낸 계획은 확정 일정처럼 보이면 안 된다 — `suggestion`은
// `planned`/`carry_over`와 다른 배지로 구분한다.
const WEEKLY_PLAN_KIND_LABELS: Record<PlanItem["kind"], string> = { planned: "확정", carry_over: "이월", suggestion: "제안" };

function WeeklyPlanBlock({ title, items }: { title: string; items: PlanItem[] }) {
  return <section><h2>{title}</h2>{items.length ? items.map((item, index) => <p key={`${item.title}-${index}`}>✓ {item.title} <span style={{ marginLeft: 8, fontSize: 11, color: item.kind === "suggestion" ? "#bd655b" : "#397454" }}>{WEEKLY_PLAN_KIND_LABELS[item.kind]}</span></p>) : <p>없음</p>}</section>;
}

export function ReportPanel({ kind }: { kind: "briefing" | "weekly" }) {
  return <ReferenceBriefingPanel kind={kind} />;
  const weekly = kind === "weekly";
  return <section className="report-panel"><div className="report-panel-heading"><div><p className="eyebrow">MAIN AGENT / {weekly ? "WEEKLY REPORT" : "TODAY BRIEFING"}</p><h2>{weekly ? "주간 업무 보고" : "오늘 브리핑"}</h2><p>{weekly ? "이번 주 업무 진행 상황과 다음 주 우선순위를 정리합니다." : "오늘 예정된 업무와 중요한 진행 상황을 한눈에 확인합니다."}</p></div><span className="report-date">{weekly ? "이번 주" : "오늘"}</span></div><div className="report-summary"><article><span>{weekly ? "완료한 업무" : "오늘의 업무"}</span><strong>{weekly ? "12건" : "5건"}</strong></article><article><span>{weekly ? "진행 중인 업무" : "우선 확인"}</span><strong>{weekly ? "7건" : "2건"}</strong></article><article><span>{weekly ? "다음 주 계획" : "회의 일정"}</span><strong>{weekly ? "4건" : "3건"}</strong></article></div><div className="report-list"><h3>{weekly ? "이번 주 주요 업무" : "오늘의 주요 업무"}</h3><p>업무 세부 내용과 상태는 프로젝트 작업 목록에서 계속 관리할 수 있습니다.</p><p>필요한 내용은 Workmate AI 채팅에서 별도로 요청할 수 있습니다.</p></div></section>;
}

export function UpdatedReportNav({ variant, activeSection, activeChat, onSelect }: { variant: UiVariant; activeSection: string; activeChat: string | null; onSelect: (section: string) => void }) {
  return <>{variant === "updated" && <div className="updated-report-nav" aria-label="업무 보고 메뉴"><button className={activeSection === "Today Briefing" ? "active" : ""} type="button" onClick={() => onSelect("Today Briefing")}>◇ 오늘 브리핑</button><button className={activeSection === "Weekly Report" ? "active" : ""} type="button" onClick={() => onSelect("Weekly Report")}>◇ 주간 업무 보고</button></div>}{activeSection === "Today Briefing" && !activeChat && <MainBriefingChatbot />}{activeChat === "Video Generation" && <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />}</>;
}


