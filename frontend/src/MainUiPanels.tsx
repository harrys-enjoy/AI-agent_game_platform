import { useState } from "react";
import type { UiVariant } from "./ui-variant";
import { useEffect } from "react";
import { quickActions } from "./ui-variant";

export function PoliciesPanel() {
  return <section className="policies-card"><div className="policies-heading"><div><p className="eyebrow">MAIN AGENT / POLICIES</p><h2>Company Policies</h2><p>팀에서 자주 확인하는 사규와 운영 기준을 한곳에서 확인하세요.</p></div><input aria-label="Search company policies" placeholder="Search policies" /></div><div className="policy-grid"><article><span>01</span><h3>근무 및 휴가</h3><p>근무시간, 휴가, 재택근무 기준</p></article><article><span>02</span><h3>보안 및 개인정보</h3><p>정보보호와 데이터 취급 기준</p></article><article><span>03</span><h3>업무 운영</h3><p>회의, 승인, 협업 운영 기준</p></article><article><span>04</span><h3>복지 및 지원</h3><p>구성원 지원 제도와 이용 안내</p></article></div></section>;
}

export function QuickActions({ variant, currentChat, onSelect }: { variant: UiVariant; currentChat: string; onSelect: (prompt: string) => void }) {
  if (variant !== "updated" || currentChat !== "Workmate AI") return null;
  return <div className="quick-actions" aria-label="Workmate AI quick actions">{quickActions.map((action) => <button type="button" className="quick-action" key={action.id} onClick={() => onSelect(action.prompt)}><span className="quick-action-icon">↗</span><span><strong>{action.label}</strong><small>{action.prompt}</small></span></button>)}</div>;
}

export function TaskQuickActions({ variant, currentChat, onSelect }: { variant: UiVariant; currentChat: string | null; onSelect: (prompt: string) => void }) {
  if (variant !== "updated" || currentChat !== "Workmate AI") return null;
  const cards = [
    { ...quickActions[0], kicker: "TASKS", title: "할 일 관리", body: "직접 등록하거나 메일·일정·회의에서 승인한 업무입니다.", detail: "전체 12 · 진행 중 4 · 지연 2", action: "할 일 등록" },
    { ...quickActions[1], kicker: "NEW MEETING", title: "회의 녹음 및 분석", body: "실시간으로 녹음하거나 기존 파일을 업로드하세요.", detail: "MP3, WAV, M4A · 최대 500MB", action: "녹음 시작" },
    { ...quickActions[2], kicker: "MEETINGS", title: "회의 관리", body: "녹음, 회의록, 분석 결과를 회의별로 확인합니다.", detail: "QA 빌드 검토 회의 · 분석 대기", action: "새 회의" },
    { ...quickActions[3], kicker: "MEETING SEARCH", title: "이전 회의록 검색", body: "회의에서 결정된 내용을 근거와 함께 찾아드립니다.", detail: "QA 빌드 일정은 어느 회의에서 결정됐어?", action: "검색" },
  ];
  const [selectedId, setSelectedId] = useState(cards[0].id);
  const selected = cards.find((card) => card.id === selectedId) ?? cards[0];
  return <section className="task-quick-actions" aria-label="Workmate AI 업무 기능"><nav className="workmate-tabs">{cards.map((card) => <button type="button" className={card.id === selected.id ? "active" : ""} key={card.id} onClick={() => { setSelectedId(card.id); onSelect(card.prompt); }}>{card.title}</button>)}</nav>{selected.id === "tasks" ? <TaskDetailPanel /> : selected.id === "recording" ? <RecordingDetailPanel /> : selected.id === "meetings" ? <MeetingsDetailPanel /> : <MeetingSearchDetailPanel />}</section>;
}

function routeMainRequest(request: string) {
  const text = request.toLowerCase();
  if (/영상|비디오|동영상|렌더|편집|자막|video|render|edit|motion/.test(text)) return "Video Generation";
  if (/개발|코드|버그|오류|api|배포|프론트|백엔드|development|code|bug|debug/.test(text)) return "Development Assistant";
  if (/게임|스토리|캐릭터|퀘스트|세계관|q&a|game|story|character|quest/.test(text)) return "Game Q&A";
  if (/업무|할 일|회의|프로젝트|마감|정책|workmate|task|meeting|project/.test(text)) return "Workmate AI";
  return null;
}

const MAIN_CHAT_API = "http://127.0.0.1:8000";

export function MainBriefingChatbot({ contextHint, owner = window.localStorage.getItem("main-assignee") ?? "default" }: { contextHint?: string; owner?: string } = {}) {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);

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
    const target = routeMainRequest(request);
    if (target) {
      const answer = `${target}로 연결합니다.`;
      setMessages((items) => [...items, { role: "assistant", text: answer }]);
      persist("assistant", answer);
      window.dispatchEvent(new CustomEvent("main-chat-route", { detail: { chat: target, message: request } }));
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("http://127.0.0.1:8000/api/chats/Main Chatbot/reply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: request }) });
      const data = response.ok ? await response.json() as { answer?: string } : {};
      const answer = data.answer ?? "질문을 확인했습니다. 업무와 관련된 내용이면 담당 Agent로 연결해 드립니다.";
      setMessages((items) => [...items, { role: "assistant", text: answer }]);
      persist("assistant", answer);
    } catch {
      const answer = "질문을 확인했습니다. 업무와 관련된 내용이면 담당 Agent로 연결해 드립니다.";
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
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder={contextHint ? "Type a message..." : "무엇을 도와드릴까요?"}
        />
        <button type="submit">➤</button>
      </form>
    </section>
  );
}

function MeetingSearchDetailPanel() {
  return <article className="meeting-search-detail"><span className="feature-kicker">MEETING SEARCH</span><h1>이전 회의록 검색</h1><p>회의에서 결정된 내용을 근거와 함께 찾아드립니다.</p><form className="meeting-search-form"><input aria-label="회의록 검색어" defaultValue="QA 빌드 일정은 어느 회의에서 결정됐어?" /><button type="submit">검색</button></form><section className="meeting-answer"><div className="answer-mark">W</div><div><span className="feature-kicker">WORKMATE ANSWER</span><h2>QA 빌드는 8월 12일 배포로 결정되었습니다.</h2><p>8월 6일 주간 개발 회의에서 회귀 테스트 일정을 고려해 배포 기준일을 8월 12일로 확정했습니다. QA팀은 8월 11일까지 최종 검증 결과를 공유하기로 했습니다.</p><blockquote><strong>주간 개발 회의</strong><span>2026.08.06 · 김서연 · 18:24</span><q>“회귀 테스트까지 반영해서 12일 빌드로 확정하겠습니다.”</q></blockquote></div></section></article>;
}

function MeetingsDetailPanel() {
  const meetings = [["07", "QA 빌드 검토 회의", "오늘 15:00 · 참여자 3명", "분석 대기"], ["04", "주간 개발 회의", "8월 6일 10:00 · 참여자 4명", "분석 완료"], ["02", "캐릭터 기획 리뷰", "8월 4일 14:00 · 참여자 5명", "분석 완료"]];
  return <article className="meetings-detail"><div className="meetings-heading"><div><span className="feature-kicker">MEETINGS</span><h1>회의 관리</h1><p>녹음, 회의록, 분석 결과를 회의별로 확인합니다.</p></div><button type="button">＋ 새 회의</button></div><div className="meeting-list">{meetings.map(([day, title, info, status]) => <div className="meeting-row" key={title}><div className="meeting-date"><strong>{day}</strong><span>AUG</span></div><div className="meeting-info"><strong>{title}</strong><span>{info}</span></div><b className={status === "분석 대기" ? "analysis-waiting" : "analysis-done"}>{status}</b><span className="meeting-arrow">⟶</span></div>)}</div></article>;
}

function RecordingDetailPanel() {
  return <article className="recording-detail"><span className="feature-kicker">NEW MEETING</span><h1>회의 녹음 및 분석</h1><p>실시간으로 녹음하거나 기존 파일을 업로드하세요.</p><div className="recording-options"><section><div className="recording-icon live">●</div><h2>실시간 녹음</h2><p>마이크 음성을 실시간 자막으로 확인합니다.</p><button type="button">녹음 시작</button></section><section><div className="recording-icon upload">⇧</div><h2>녹음 파일 업로드</h2><p>MP3, WAV, M4A · 최대 500MB</p><label className="upload-button">파일 선택<input type="file" accept="audio/mpeg,audio/wav,audio/x-m4a,.mp3,.wav,.m4a" /></label></section></div></article>;
}

function TaskDetailPanel() {
  const rows = [
    ["QA 서버 빌드 배포", "이병준", "진행 중", "오늘 18:00", "높음"],
    ["로그인 오류 원인 분석", "김서연", "지연", "8월 6일", "긴급"],
    ["신규 캐릭터 밸런스 검토", "이병준", "할 일", "내일 12:00", "보통"],
    ["상점 UI 문구 검수", "박지훈", "할 일", "8월 11일", "낮음"],
  ];
  return <article className="task-detail-panel"><div className="task-detail-heading"><div><span className="feature-kicker">TASKS</span><h1>할 일 관리</h1><p>직접 등록하거나 메일·일정·회의에서 승인한 업무입니다.</p></div><button type="button">＋ 할 일 등록</button></div><div className="task-toolbar"><div className="task-filters"><button className="active" type="button">전체 12</button><button type="button">진행 중 4</button><button type="button">지연 2</button></div><input aria-label="할 일 검색" placeholder="할 일 검색" /></div><div className="task-table"><div className="task-table-head"><span>할 일</span><span>담당자</span><span>상태</span><span>마감</span><span>중요도</span></div>{rows.map((row) => <div className="task-table-row" key={row[0]}><span>{row[0]}</span><span>{row[1]}</span><span><b className={`task-status ${row[2] === "지연" ? "delayed" : row[2] === "진행 중" ? "progress" : "todo"}`}>{row[2]}</b></span><span>{row[3]}</span><span>{row[4]}</span></div>)}</div></article>;
}

export function ReferenceBriefingPanel({ kind, assigneeName = "병준", onConfirm }: { kind: "briefing" | "weekly"; assigneeName?: string; onConfirm?: () => void }) {
  const weekly = kind === "weekly";
  return <section className="report-panel report-dashboard"><div className="briefing-header"><div><span className="briefing-date">2026년 8월 7일 금요일</span><h1>{weekly ? "이번 주 업무 보고" : `좋은 아침이에요, ${assigneeName}님.`}</h1><p>{weekly ? "이번 주 업무 진행 상황과 다음 주 계획을 한눈에 확인하세요." : "오늘은 회의 3개와 마감 업무 2개가 있습니다."}</p></div><button className="refresh-report" type="button">↻ 새로고침</button></div><div className="signal-strip"><span>● Task 최신</span><span>● Calendar 1분 전</span><span>● Gmail 일부 지연</span><span>● Meeting 최신</span></div><div className="briefing-section-title"><span>FOCUS</span><h2>{weekly ? "이번 주 우선순위 Top 3" : "오늘의 우선순위 Top 3"}</h2><small>09:02 계산</small></div><div className="priority-grid"><article className="priority-card featured"><b>1</b><strong>QA 서버 빌드 배포</strong><span>{weekly ? "이번 주 완료 · 개발팀" : "오늘 18:00 · 개발팀"}</span><em>85점</em><hr/><small>오늘 마감 · 중요도 높음 · 15시 QA 회의</small></article><article className="priority-card"><b>2</b><strong>로그인 오류 원인 분석</strong><span>1일 지연 · 클라이언트팀</span><em>78점</em><hr/><small>기한 초과 · 다른 업무 차단</small></article><article className="priority-card"><b>3</b><strong>신규 캐릭터 밸런스 검토</strong><span>내일 12:00 · 기획팀</span><em>64점</em><hr/><small>회의 Action Item · 내일 마감</small></article></div><div className="briefing-columns"><section className="briefing-list"><h2>{weekly ? "이번 주 주요 업무" : "오늘 일정"} <small>{weekly ? "4건" : "3개"}</small></h2><div><b>{weekly ? "월" : "10:00"}</b><strong>데일리 스크럼</strong><span>개발팀 · 30분</span></div><div><b>{weekly ? "수" : "15:00"}</b><strong>QA 빌드 검토</strong><span>QA팀 · 1시간</span></div><div><b>{weekly ? "금" : "17:00"}</b><strong>캐릭터 기획 리뷰</strong><span>기획팀 · 1시간</span></div></section><section className="briefing-list"><h2>중요 업무 신호 <small>2개</small></h2><div><b className="signal-red">M</b><strong>[QA] 빌드 배포 일정 확인 요청</strong><span>마감일이 포함된 할 일 후보입니다.</span><a>할 일 추가</a></div><div><b className="signal-blue">C</b><strong>스토어 심사 제출</strong><span>아직 할 일로 등록되지 않은 일정입니다.</span><a>할 일 추가</a></div></section></div></section>;
}

export function WeeklyReportPanel({ onConfirm }: { onConfirm?: () => void }) {
  return <section className="report-panel weekly-dashboard"><div className="weekly-header"><div><span>8월 3일 — 8월 9일</span><h1>주간 업무보고</h1><p>이번 주 업무와 회의 내용을 근거로 정리했습니다.</p></div><button type="button">Markdown 복사</button></div><div className="weekly-metrics"><article><strong>8</strong><span>완료 업무</span></article><article><strong>4</strong><span>진행 중</span></article><article className="delayed"><strong>2</strong><span>지연 업무</span></article><article><strong>6</strong><span>주요 회의</span></article></div><div className="weekly-report-grid"><section><h2>완료 업무</h2><p>✓ QA 서버 배포 자동화 스크립트 적용</p><p>✓ 신규 캐릭터 스킬 명세 검토</p><p>✓ 로그인 수집 정책과 대시보드 지표 확정</p></section><section><h2>진행 중 업무</h2><p>✓ 로그인 오류 재현 및 원인 분석 — 70%</p><p>✓ 스토어 심사 자료 작성 — 45%</p></section><section><h2>주요 회의 내용</h2><p>✓ 8월 12일 QA 빌드를 기준으로 회귀 테스트 진행</p><p>✓ 캐릭터 밸런스 수치는 다음 기획 리뷰에서 최종 확정</p></section><section><h2>다음 주 계획</h2><p>✓ 신규 캐릭터 QA 진행 (Task 근거)</p><p>✓ 스토어 심사 제출 (Calendar 근거)</p></section></div></section>;
}

export function ReportPanel({ kind }: { kind: "briefing" | "weekly" }) {
  return <ReferenceBriefingPanel kind={kind} />;
  const weekly = kind === "weekly";
  return <section className="report-panel"><div className="report-panel-heading"><div><p className="eyebrow">MAIN AGENT / {weekly ? "WEEKLY REPORT" : "TODAY BRIEFING"}</p><h2>{weekly ? "주간 업무 보고" : "오늘 브리핑"}</h2><p>{weekly ? "이번 주 업무 진행 상황과 다음 주 우선순위를 정리합니다." : "오늘 예정된 업무와 중요한 진행 상황을 한눈에 확인합니다."}</p></div><span className="report-date">{weekly ? "이번 주" : "오늘"}</span></div><div className="report-summary"><article><span>{weekly ? "완료한 업무" : "오늘의 업무"}</span><strong>{weekly ? "12건" : "5건"}</strong></article><article><span>{weekly ? "진행 중인 업무" : "우선 확인"}</span><strong>{weekly ? "7건" : "2건"}</strong></article><article><span>{weekly ? "다음 주 계획" : "회의 일정"}</span><strong>{weekly ? "4건" : "3건"}</strong></article></div><div className="report-list"><h3>{weekly ? "이번 주 주요 업무" : "오늘의 주요 업무"}</h3><p>업무 세부 내용과 상태는 프로젝트 작업 목록에서 계속 관리할 수 있습니다.</p><p>필요한 내용은 Workmate AI 채팅에서 별도로 요청할 수 있습니다.</p></div></section>;
}

export function UpdatedReportNav({ variant, activeSection, activeChat, onSelect }: { variant: UiVariant; activeSection: string; activeChat: string | null; onSelect: (section: string) => void }) {
  return <>{variant === "updated" && <div className="updated-report-nav" aria-label="업무 보고 메뉴"><button className={activeSection === "Today Briefing" ? "active" : ""} type="button" onClick={() => onSelect("Today Briefing")}>◇ 오늘 브리핑</button><button className={activeSection === "Weekly Report" ? "active" : ""} type="button" onClick={() => onSelect("Weekly Report")}>◇ 주간 업무 보고</button></div>}{activeSection === "Today Briefing" && !activeChat && <MainBriefingChatbot />}{activeChat === "Video Generation" && <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />}</>;
}


