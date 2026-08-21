import { FormEvent, useEffect, useRef, useState } from "react";
import PreviewPanel from "./PreviewPanel";
import "./chat-answer.css";
import { selectMenu } from "./menu-utils";
import { createChatReply, createTask, createTaskProposal, getTaskAction, mapTaskStatus, pollTask, shouldApplyChatResponse, updateTask } from "./task-utils";
import "./task-form.css";
import { commandCatalog, getCommandInputValue, resolveChatCommand } from "./command-utils";
import { extractArtPrompt, formatArtPromptForChat, type ArtPrompt } from "./art-prompt-utils";
import { scrollChatToBottom } from "./chat-scroll";
import { buildStoryDraft, canApproveStory, reviewLabel, type StoryDraft, type StoryReview } from "./story-review-utils";
import { buildResumeFormData, buildUnresolvedScenes, finalVideoMessageText, markSceneStatus, mergeResumeResult, type RawUnresolvedScene, type ResumeResult, type UnresolvedScene } from "./resume-utils";
import { PoliciesPanel, QuickActions, ReferenceBriefingPanel, ReportPanel, TaskQuickActions, UpdatedReportNav, WeeklyReportPanel } from "./MainUiPanels";
import { AssigneeAssignments, assigneeOptions, defaultAssignments, findAssignee } from "./assignee";
import { AssigneeSwitcher } from "./AssigneeSwitcher";
import { VideoAgentPage } from "./video-agent/VideoAgentPage";
import { routeAgentRequest } from "./agent-routing";
import GameQnaSummary from "./GameQnaSummary";
import { normalizeAgentWorkTasks, syncGameQnaStoryReviewTask } from "./chat-task-utils";
import { createRecentGameQnaWork, upsertRecentGameQnaWork, type RecentGameQnaWork } from "./game-qna-summary-utils";
import TaskLogPanel from "./TaskLogPanel";

const API_BASE_URL = "http://127.0.0.1:8000";
type Task = { id: string; name: string; owner: string; status: string; agent: string };
type ChatTask = { id: string; chat: string; title: string; status: "working" | "done" | "error"; hidden: boolean; owner?: string };
// `assistant_ask`(workmate-agent)가 확인이 필요한 동작(예: analyze_meeting)을
// 골랐을 때 돌려주는 {skill_id, arguments} — 사용자가 "확인"을 누르면 이 값을
// 그대로 `ChatReplyRequest.confirmed_skill_id`/`confirmed_arguments`에 실어
// 재전송한다(20번 문서 G5 대응, 2026-08-19).
type PendingAction = { skill_id: string; arguments: Record<string, unknown> };
type ChatMessage = { id: string; kind: "text"; text: string } | { id: string; kind: "proposal"; proposal: Task; state: "pending" | "adding" | "added" | "cancelled" | "error" } | { id: string; kind: "unresolved-scenes"; taskId: string; scenes: UnresolvedScene[] } | { id: string; kind: "pending-action"; action: PendingAction; chatName: string; text: string; state: "pending" | "confirming" | "done" | "cancelled" | "error" };
type StoredMessage = { id: string; role: "user" | "assistant" | "system"; content: string; pending_action?: PendingAction | null };
const legacySections = ["Today Briefing", "Weekly Report", "Policies"];
const chats = ["Workmate AI", "Video Generation", "Development Assistant", "Game Q&A"];
const statuses = ["Ready to start", "In Progress", "Done", "Stuck", "Waiting for review"];
const initialTasks: Task[] = [
  { id: "1", name: "게임 Q&A 지식 검색", owner: "PW", status: "Done", agent: "Game Q&A" },
  { id: "2", name: "영상 기획 초안 생성", owner: "T", status: "In Progress", agent: "Video Generation" },
  { id: "3", name: "PR 변경사항 검토", owner: "", status: "Ready to start", agent: "Development Assistant" },
];

function agentWorkStorageKey(owner: string) {
  return `ai-chat-tasks:${owner}`;
}

function loadAgentWorkTasks(owner: string): ChatTask[] {
  try {
    const scoped = window.localStorage.getItem(agentWorkStorageKey(owner));
    if (scoped) return normalizeAgentWorkTasks(JSON.parse(scoped) as ChatTask[]).map((item) => ({ ...item, owner }));
    const legacy = window.localStorage.getItem("ai-chat-tasks");
    if (!legacy) return [];
    const migrated = normalizeAgentWorkTasks(JSON.parse(legacy) as ChatTask[]).map((item) => ({ ...item, owner }));
    window.localStorage.setItem(agentWorkStorageKey(owner), JSON.stringify(migrated));
    return migrated;
  } catch {
    return [];
  }
}

// 저장된 대화 이력을 화면 `ChatMessage[]`로 되살린다. `pending_action`이 있는 assistant
// 메시지라도 **세션의 마지막 메시지일 때만** 확인/취소 카드로 되살린다 — 그 뒤에 이미
// 다른 메시지(확인 결과·취소 안내 등)가 쌓였다면 이미 처리된 요청이라는 뜻이라 평문으로만
// 보여준다(두 번 실행되는 사고를 막는다, 2026-08-19). 카드를 다시 그리려면 재전송에 쓸
// 원래 요청 문장이 필요한데, 저장 당시의 `text`를 따로 안 남겼으므로 바로 앞 user 메시지를
// 그 문장으로 재사용한다(`submit()`이 카드를 만들 때와 같은 값).
function rebuildChatFromHistory(messages: StoredMessage[], chatName: string): ChatMessage[] {
  const lastIndex = messages.length - 1;
  return messages.map((item, index) => {
    if (item.role === "assistant" && index === lastIndex && item.pending_action?.skill_id) {
      const previousUser = [...messages.slice(0, index)].reverse().find((entry) => entry.role === "user");
      return { id: item.id, kind: "pending-action", action: { skill_id: item.pending_action.skill_id, arguments: item.pending_action.arguments ?? {} }, chatName, text: previousUser?.content ?? "", state: "pending" };
    }
    const prompt = chatName === "Game Q&A" && item.role === "assistant" ? extractArtPrompt(item.content) : null;
    return { id: item.id, kind: "text", text: item.role === "user" ? `You: ${item.content}` : prompt ? formatArtPromptForChat(prompt) : item.content };
  });
}

// 확인 카드가 떠 있을 때(state="pending") 사용자가 짧게 긍정/부정만 답하면, 그걸 새 질문으로
// 워크메이트에 보내는 대신 바로 그 카드의 확인/취소를 누른 것처럼 처리한다 — 이 채팅 경로는
// 대화 이력을 워크메이트에 보내지 않아(20번 문서 참고) LLM에게 "응"이 뭘 가리키는지 판단하게
// 맡길 수 없다. LLM을 타지 않는 결정론적 매칭이라 오탐 위험이 낮게 정확히 일치할 때만 잡는다.
const PENDING_ACTION_CONFIRM_WORDS = new Set(["응", "네", "넵", "예", "확인", "좋아", "오케이", "ok", "okay", "yes", "y"]);
const PENDING_ACTION_CANCEL_WORDS = new Set(["아니", "아니요", "아니오", "취소", "no", "n"]);

export default function App() {
  const [tasks, setTasks] = useState(initialTasks);
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [mainChat, setMainChat] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [mainMessage, setMainMessage] = useState("");
  const [mainChatBusy, setMainChatBusy] = useState(false);
  const [chatSessions, setChatSessions] = useState<Record<string, string>>({});
  const [activeSection, setActiveSection] = useState("Today Briefing");
  const [activeChat, setActiveChat] = useState<string | null>(null);
  const [worksOpen, setWorksOpen] = useState(true);
  const [policiesOpen, setPoliciesOpen] = useState(true);
  const [policyView, setPolicyView] = useState<"company" | "operations">("operations");
  const [aiChatsOpen, setAiChatsOpen] = useState(false);
  const [assigneeName, setAssigneeName] = useState(() => window.localStorage.getItem("main-assignee") ?? assigneeOptions[0].name);
  const [chatTasks, setChatTasks] = useState<ChatTask[]>(() => loadAgentWorkTasks(assigneeName));
  const [recentGameQnaWorks, setRecentGameQnaWorks] = useState<RecentGameQnaWork[]>(() => { try { const saved = JSON.parse(window.localStorage.getItem("game-qna-recent-work") ?? "[]") as RecentGameQnaWork | RecentGameQnaWork[]; return Array.isArray(saved) ? saved.slice(0, 3) : saved ? [saved] : []; } catch { return []; } });
  const [pendingArtPrompt, setPendingArtPrompt] = useState<ArtPrompt | null>(() => { try { return JSON.parse(window.localStorage.getItem("game-qna-art-prompt") ?? "null") as ArtPrompt | null; } catch { return null; } });
  const [artPromptTransferStatus, setArtPromptTransferStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  // 19번 문서 결정 4 — 회의 녹음 중 사이드바로 다른 화면/담당자로 이동하면
  // WebSocket이 끊겨 서버가 그 시점까지 받은 Chunk로 세션을 자동 확정한다.
  // `TaskQuickActions`가 녹음 시작/종료를 여기로 올려보내고, 아래 이동 핸들러들이
  // 이 플래그를 보고 확인창을 띄운다("Workmate AI" 탭 내부 이동은 TaskQuickActions가
  // 자체적으로 같은 확인창을 띄우니 여기선 안 겹친다).
  const [isRecordingMeeting, setIsRecordingMeeting] = useState(false);
  function confirmLeaveRecording(): boolean {
    return !isRecordingMeeting || window.confirm("녹음 중입니다. 이동하면 녹음이 종료됩니다. 이동할까요?");
  }
  const [assignments, setAssignments] = useState<AssigneeAssignments>(() => { try { return { ...defaultAssignments, ...JSON.parse(window.localStorage.getItem("assignee-assignments") ?? "{}") }; } catch { return defaultAssignments; } });
  const [isAddingTask, setIsAddingTask] = useState(false);
  const [newTaskName, setNewTaskName] = useState("");
  const [newTaskAgent, setNewTaskAgent] = useState(chats[0]);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [draftTask, setDraftTask] = useState<Task | null>(null);
  const [isStoryFormOpen, setIsStoryFormOpen] = useState(false);
  const [storyName, setStoryName] = useState("");
  const [storyKeywords, setStoryKeywords] = useState("");
  const [storyAnswer, setStoryAnswer] = useState("");
  const [storyNotice, setStoryNotice] = useState("");
  const [storyDraft, setStoryDraft] = useState<StoryDraft | null>(null);
  const [storyReview, setStoryReview] = useState<StoryReview | null>(null);
  const [isReviewingStory, setIsReviewingStory] = useState(false);
  const [showCommandHelp, setShowCommandHelp] = useState(false);
  const currentChat = activeChat ?? "Workmate AI";
  const recentGameQnaWork = recentGameQnaWorks;
  const currentAssignee = findAssignee(assigneeName);
  const currentSessionKey = `${assigneeName}::${currentChat}`;
  const currentSessionId = chatSessions[currentSessionKey];
  const activeChatRef = useRef(currentChat);
  const messagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeSection === "Company Policies") {
      setPolicyView("company");
      setActiveSection("Policies");
    } else if (activeSection === "Operational Policies") {
      setPolicyView("operations");
      setActiveSection("Policies");
    }
  }, [activeSection]);

  useEffect(() => {
    setChatTasks(loadAgentWorkTasks(assigneeName));
  }, [assigneeName]);

  function recordGameQnaWork(request: string, status = "완료") {
    const work = createRecentGameQnaWork(request, status);
    setRecentGameQnaWorks((items) => {
      const next = upsertRecentGameQnaWork(items, work);
      window.localStorage.setItem("game-qna-recent-work", JSON.stringify(next));
      return next;
    });
  }

  async function sendArtPromptToVideo() {
    let artPromptToSend = pendingArtPrompt;
    try {
      const stored = JSON.parse(window.localStorage.getItem("game-qna-art-prompt") ?? "null");
      if (stored && typeof stored === "object" && !Array.isArray(stored)) artPromptToSend = stored as ArtPrompt;
    } catch {
      // Keep the last valid in-memory prompt when local storage was manually corrupted.
    }
    if (!artPromptToSend || artPromptTransferStatus === "sending") return;
    setArtPromptTransferStatus("sending");
    try {
      const response = await fetch(`${API_BASE_URL}/api/game-qna/art-prompts/send-to-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ art_prompt: artPromptToSend }),
      });
      if (!response.ok) throw new Error("Video Agent handoff failed");
      setArtPromptTransferStatus("sent");
      recordGameQnaWork("/art video handoff", "전송 완료");
    } catch {
      setArtPromptTransferStatus("error");
    }
  }

  useEffect(() => {
    scrollChatToBottom(messagesRef.current);
  }, [chat, currentChat]);

  useEffect(() => {
    let cancelled = false;
    setMainChat([]);
    fetch(`${API_BASE_URL}/api/chats/Main%20Chatbot/session?owner=${encodeURIComponent(assigneeName)}`)
      .then((response) => response.ok ? response.json() as Promise<{ messages: StoredMessage[] }> : Promise.reject(new Error("Main Chatbot history failed")))
      .then((session) => {
        if (!cancelled) setMainChat(session.messages.filter((item) => item.role === "user" || item.role === "assistant").map((item) => ({ role: item.role as "user" | "assistant", text: item.content })));
      })
      .catch(() => { if (!cancelled) setMainChat([]); });
    return () => { cancelled = true; };
  }, [assigneeName]);

  useEffect(() => {
    function routeFromMain(event: Event) {
      const detail = (event as CustomEvent<{ chat: string; message: string }>).detail;
      if (!detail?.chat) return;
      activateChatTask(detail.chat);
      activeChatRef.current = detail.chat;
      setActiveSection("Home");
      setActiveChat(detail.chat);
      setMessage(detail.message);
    }
    window.addEventListener("main-chat-route", routeFromMain);
    return () => window.removeEventListener("main-chat-route", routeFromMain);
  }, []);

  useEffect(() => {
    function handleStoryReviewState(event: Event) {
      const state = (event as CustomEvent<{ status?: "working" | "done" | "error" }>).detail?.status;
      if (!state) return;
      recordGameQnaWork("/story-review", state === "working" ? "검토 중" : state === "done" ? "검토 완료" : "오류");
      setAiChatsOpen(true);
      setChatTasks((items) => {
        const next = syncGameQnaStoryReviewTask(items, state, `game-qna-${Date.now()}`);
        window.localStorage.setItem(agentWorkStorageKey(assigneeName), JSON.stringify(next.map((item) => ({ ...item, owner: assigneeName }))));
        return next;
      });
    }
    window.addEventListener("game-qna-story-review-state", handleStoryReviewState);
    return () => window.removeEventListener("game-qna-story-review-state", handleStoryReviewState);
  }, []);

  useEffect(() => {
    activeChatRef.current = currentChat;
    let cancelled = false;
    setChat([]);
    fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/session?owner=${encodeURIComponent(assigneeName)}`)
      .then((response) => response.ok ? response.json() as Promise<{ session_id: string; messages: StoredMessage[] }> : Promise.reject(new Error("Chat history failed")))
      .then((session) => { if (!cancelled) { setChatSessions((items) => ({ ...items, [currentSessionKey]: session.session_id })); setChat(rebuildChatFromHistory(session.messages, currentChat)); } })
      .catch(() => { if (!cancelled) setChat([]); });
    return () => { cancelled = true; };
  }, [currentChat, assigneeName]);

  function persistMessage(role: "user" | "assistant", content: string, pendingAction?: PendingAction | null) {
    void fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role, content, session_id: currentSessionId, owner: assigneeName, pending_action: pendingAction ?? null }) }).catch(() => undefined);
  }

  function persistMainMessage(role: "user" | "assistant", content: string) {
    void fetch(`${API_BASE_URL}/api/chats/Main%20Chatbot/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role, content, owner: assigneeName }) }).catch(() => undefined);
  }

  function routeBriefingRequest(request: string) {
    const text = request.toLowerCase();
    if (/영상|비디오|동영상|렌더|편집|자막|video|render|edit|motion/.test(text)) return "Video Generation";
    if (/개발|코드|버그|오류|api|배포|프론트|백엔드|development|code|bug|debug/.test(text)) return "Development Assistant";
    if (/게임|스토리|캐릭터|퀘스트|세계관|q&a|game|story|character|quest/.test(text)) return "Game Q&A";
    return "Workmate AI";
  }

  async function submitMainChat(event: FormEvent) {
    event.preventDefault();
    const request = mainMessage.trim();
    if (!request || mainChatBusy) return;
    setMainMessage("");
    setMainChat((items) => [...items, { role: "user", text: request }]);
    persistMainMessage("user", request);
    const agent = routeBriefingRequest(request);
    const isAgentRequest = agent !== "Workmate AI" || /업무|할 일|회의|프로젝트|마감|정책|workmate/i.test(request);
    if (isAgentRequest) {
      const target = agent === "Workmate AI" ? "Workmate AI" : agent;
      activateChatTask(target);
      const routingMessage = `${target}로 연결합니다.`;
      setMainChat((items) => [...items, { role: "assistant", text: routingMessage }]);
      persistMainMessage("assistant", routingMessage);
      setTimeout(() => { activeChatRef.current = target; setActiveSection("Home"); setActiveChat(target); setMessage(request); }, 0);
      return;
    }
    setMainChatBusy(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/Main Chatbot/reply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: request }) });
      const data = response.ok ? await response.json() as { answer?: string } : {};
      const answer = data.answer ?? createChatReply(request);
      setMainChat((items) => [...items, { role: "assistant", text: answer }]);
      persistMainMessage("assistant", answer);
    } catch {
      const answer = createChatReply(request);
      setMainChat((items) => [...items, { role: "assistant", text: answer }]);
      persistMainMessage("assistant", answer);
    } finally { setMainChatBusy(false); }
  }

  async function resetChat() {
    const response = await fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/reset?owner=${encodeURIComponent(assigneeName)}`, { method: "POST" });
    if (!response.ok) return;
    const data = await response.json() as { session_id: string };
    setChatSessions((items) => ({ ...items, [currentSessionKey]: data.session_id }));
    setChat([]);
  }

  function handleSectionClick(section: string) { if (!confirmLeaveRecording()) return; const state = section === "Today Briefing" || section === "Weekly Report" ? { activeSection: section, activeChat: null } : selectMenu({ type: "section", id: section }); activeChatRef.current = state.activeChat ?? "Workmate AI"; setActiveSection(state.activeSection); setActiveChat(state.activeChat); }
  function saveAgentWorkTasks(next: ChatTask[]) { const scoped = next.map((item) => ({ ...item, owner: assigneeName })); window.localStorage.setItem(agentWorkStorageKey(assigneeName), JSON.stringify(scoped)); return scoped; }
  function activateChatTask(chatName: string) { setChatTasks((items) => { const existing = items.find((item) => item.chat === chatName); const next = existing ? items.map((item) => item.id === existing.id ? { ...item, hidden: false, status: "done" as const } : item) : [...items, { id: `chat-task-${Date.now()}`, chat: chatName, title: `${chatName} 작업`, status: "done" as const, hidden: false, owner: assigneeName }]; return saveAgentWorkTasks(next); }); }
  function startChatTask(chatName: string) { setChatTasks((items) => saveAgentWorkTasks(items.map((item) => item.chat === chatName && !item.hidden ? { ...item, status: "working" as const } : item))); }
  function completeChatTask(chatName: string) { setChatTasks((items) => saveAgentWorkTasks(items.map((item) => item.chat === chatName && !item.hidden ? { ...item, status: "done" as const } : item))); }
  function hideChatTask(taskId: string) { setChatTasks((items) => saveAgentWorkTasks(items.map((item) => item.id === taskId ? { ...item, hidden: true } : item))); }
  function handleChatClick(chatName: string) { if (!confirmLeaveRecording()) return; activateChatTask(chatName); const state = selectMenu({ type: "chat", id: chatName }, activeSection); activeChatRef.current = state.activeChat ?? "Workmate AI"; setActiveSection(state.activeSection); setActiveChat(state.activeChat); }
  function changeAssignee(name: string) { if (!confirmLeaveRecording()) return; setAssigneeName(name); window.localStorage.setItem("main-assignee", name); activeChatRef.current = "Workmate AI"; setActiveSection("Today Briefing"); setActiveChat(null); }
  function saveAssignments(next: AssigneeAssignments) { setAssignments(next); window.localStorage.setItem("assignee-assignments", JSON.stringify(next)); }
  function confirmReport() { activeChatRef.current = currentAssignee.chat; setActiveSection("Home"); setActiveChat(currentAssignee.chat); }
  function selectQuickAction(prompt: string) { setActiveSection("Home"); setActiveChat("Workmate AI"); activeChatRef.current = "Workmate AI"; setMessage(prompt); }
  function addTask(event: FormEvent) { event.preventDefault(); const task = createTask(newTaskName, newTaskAgent, `task-${Date.now()}`); if (!task) return; setTasks((items) => [...items, task]); setNewTaskName(""); setIsAddingTask(false); }
  function startEdit(task: Task) { setEditingTaskId(task.id); setDraftTask({ ...task }); }
  function cancelEdit() { setEditingTaskId(null); setDraftTask(null); }
  function commitEdit() { if (!draftTask) return; setTasks((items) => items.map((item) => item.id === draftTask.id ? updateTask(item, { owner: draftTask.owner, status: draftTask.status, agent: draftTask.agent }) : item)); cancelEdit(); }

  async function addStory(event: FormEvent) {
    event.preventDefault();
    setStoryNotice("");
    setIsReviewingStory(true);
    try {
      const draft = buildStoryDraft(storyName, storyKeywords, storyAnswer);
      const response = await fetch(`${API_BASE_URL}/api/stories/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...draft, owner: assigneeName }),
      });
      if (!response.ok) throw new Error("Story review API failed");
      const review = await response.json() as StoryReview;
      setStoryDraft(draft);
      setStoryReview(review);
      setStoryNotice(`Review complete: ${reviewLabel(review)}. Approval is required before saving.`);
      if (canApproveStory(review) && window.confirm("검토를 통과했습니다. Catalog에 저장할까요?")) {
        const approval = await fetch(`${API_BASE_URL}/api/stories/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reviewId: review.reviewId, draft }),
        });
        if (!approval.ok) throw new Error("Story approval API failed");
        setStoryName(""); setStoryKeywords(""); setStoryAnswer(""); setStoryDraft(null); setStoryReview(null);
        setStoryNotice("Story approved and saved to Catalog.");
      }
    } catch { setStoryNotice("Story could not be reviewed. Check the Catalog connection."); }
    finally { setIsReviewingStory(false); }
  }

  async function approveStory() {
    if (!storyDraft || !storyReview || !canApproveStory(storyReview)) return;
    setStoryNotice("Saving approved story...");
    try {
      const response = await fetch(`${API_BASE_URL}/api/stories/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewId: storyReview.reviewId, draft: storyDraft }),
      });
      if (!response.ok) throw new Error("Story approval API failed");
      setStoryName(""); setStoryKeywords(""); setStoryAnswer(""); setStoryDraft(null); setStoryReview(null);
      setStoryNotice("Story approved and saved to Catalog.");
    } catch { setStoryNotice("Story could not be saved. Review may have expired."); }
  }

  async function confirmProposal(proposalId: string) {
    const proposalMessage = chat.find((item) => item.id === proposalId && item.kind === "proposal");
    if (!proposalMessage || proposalMessage.kind !== "proposal" || proposalMessage.state !== "pending") return;
    setChat((items) => items.map((item) => item.id === proposalId && item.kind === "proposal" ? { ...item, state: "adding" } : item));
    try {
      const response = await fetch(`${API_BASE_URL}/api/tasks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request: proposalMessage.proposal.name }) });
      if (!response.ok) throw new Error("Task API failed");
      const data = await response.json() as { task_id: string; status?: string };
      const taskId = data.task_id;
      setTasks((items) => [...items, { ...proposalMessage.proposal, id: taskId, status: mapTaskStatus(data.status ?? "queued") }]);
      setChat((items) => items.map((item) => item.id === proposalId && item.kind === "proposal" ? { ...item, state: "added" } : item));
      persistMessage("assistant", `Task added to Project Task: ${proposalMessage.proposal.name}`);
      try {
        const task = await pollTask(taskId, (path) => fetch(`${API_BASE_URL}${path}`));
        setTasks((items) => items.map((item) => item.id === taskId ? { ...item, status: mapTaskStatus(task.status) } : item));
      } catch {
        setTasks((items) => items.map((item) => item.id === taskId ? { ...item, status: "Stuck" } : item));
      }
    } catch { setChat((items) => items.map((item) => item.id === proposalId && item.kind === "proposal" ? { ...item, state: "error" } : item)); persistMessage("assistant", "Task could not be added. Check the API connection."); }
  }

  function cancelProposal(proposalId: string) { setChat((items) => items.map((item) => item.id === proposalId && item.kind === "proposal" ? { ...item, state: "cancelled" } : item)); persistMessage("assistant", "Task addition cancelled."); }

  async function confirmPendingAction(actionId: string) {
    const item = chat.find((entry) => entry.id === actionId);
    if (!item || item.kind !== "pending-action" || item.state !== "pending") return;
    setChat((items) => items.map((entry) => entry.id === actionId && entry.kind === "pending-action" ? { ...entry, state: "confirming" } : entry));
    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(item.chatName)}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: item.text, owner: assigneeName, confirmed_skill_id: item.action.skill_id, confirmed_arguments: item.action.arguments }),
      });
      if (!response.ok) throw new Error(`Agent reply failed (${response.status})`);
      const data = await response.json() as { answer?: string; pending_action?: { skill_id?: string; arguments?: Record<string, unknown> } | null };
      const reply = data.answer || "실행됐습니다.";
      // 방금 실행한 Skill(예: analyze_meeting) 결과가 또 다른 확인을 요구할 수 있다 —
      // 예를 들어 분석 뒤 "이 Action Item을 할 일로 추가할까요?"(review_action_items)가
      // 이어 붙는 경우. 이때도 텍스트로만 끝내지 않고 새 확인 카드를 이어 붙인다(2026-08-19,
      // 실사용 중 "응"에 아무 반응이 없던 문제의 원인).
      const nextPendingAction: PendingAction | null = data.pending_action?.skill_id
        ? { skill_id: data.pending_action.skill_id, arguments: data.pending_action.arguments ?? {} }
        : null;
      persistMessage("assistant", reply, nextPendingAction);
      const nextPendingActionMessage: ChatMessage | null = nextPendingAction
        ? { id: `pending-action-${Date.now()}`, kind: "pending-action", action: nextPendingAction, chatName: item.chatName, text: item.text, state: "pending" }
        : null;
      setChat((items) => [
        ...items.map((entry): ChatMessage => entry.id === actionId && entry.kind === "pending-action" ? { ...entry, state: "done" as const } : entry),
        { id: `confirmed-${Date.now()}`, kind: "text", text: reply },
        ...(nextPendingActionMessage ? [nextPendingActionMessage] : []),
      ]);
    } catch {
      setChat((items) => items.map((entry) => entry.id === actionId && entry.kind === "pending-action" ? { ...entry, state: "error" } : entry));
      persistMessage("assistant", "실행에 실패했습니다. 다시 시도해 주세요.");
    }
  }

  function cancelPendingAction(actionId: string) { setChat((items) => items.map((entry) => entry.id === actionId && entry.kind === "pending-action" ? { ...entry, state: "cancelled" } : entry)); persistMessage("assistant", "요청을 취소했습니다."); }

  async function uploadSceneFix(messageId: string, taskId: string, sceneId: string, file: File) {
    setChat((items) => items.map((item) => item.id === messageId && item.kind === "unresolved-scenes" ? { ...item, scenes: markSceneStatus(item.scenes, sceneId, "uploading") } : item));
    try {
      const response = await fetch(`${API_BASE_URL}/api/video-agent/tasks/${encodeURIComponent(taskId)}/scenes/${encodeURIComponent(sceneId)}/resume`, { method: "POST", body: buildResumeFormData(file) });
      if (!response.ok) throw new Error(`Resume upload failed (${response.status})`);
      const result = await response.json() as ResumeResult;
      setChat((items) => items.map((item) => item.id === messageId && item.kind === "unresolved-scenes" ? { ...item, scenes: mergeResumeResult(item.scenes, result) } : item));
      const outputVideoUrl = result.output_video_url;
      if (result.remaining_unresolved.length === 0 && outputVideoUrl) {
        setChat((items) => [...items, { id: `video-ready-${Date.now()}`, kind: "text", text: finalVideoMessageText(outputVideoUrl) }]);
      }
    } catch {
      setChat((items) => items.map((item) => item.id === messageId && item.kind === "unresolved-scenes" ? { ...item, scenes: markSceneStatus(item.scenes, sceneId, "error") } : item));
    }
  }

  function selectGameQaCommand(command: string) {
    const resolved = resolveChatCommand(command);
    if (resolved.kind !== "request") return;
    setMessage(getCommandInputValue(resolved.command ?? command));
    setShowCommandHelp(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); if (!message.trim()) return;
    const request = message.trim(); setMessage("");
    // 화면에 확인 카드가 떠 있는 상태(state="pending")에서 짧은 긍정/부정만 답하면, 새
    // 질문으로 보내는 대신 그 카드의 확인/취소를 누른 것처럼 처리한다(위
    // `PENDING_ACTION_CONFIRM_WORDS`/`PENDING_ACTION_CANCEL_WORDS` 주석 참고).
    const lastChatItem = chat[chat.length - 1];
    if (lastChatItem?.kind === "pending-action" && lastChatItem.state === "pending") {
      const normalized = request.toLowerCase();
      const isConfirm = PENDING_ACTION_CONFIRM_WORDS.has(normalized);
      const isCancel = !isConfirm && PENDING_ACTION_CANCEL_WORDS.has(normalized);
      if (isConfirm || isCancel) {
        setChat((items) => [...items, { id: `message-${Date.now()}`, kind: "text", text: `You: ${request}` }]);
        persistMessage("user", request);
        if (isConfirm) void confirmPendingAction(lastChatItem.id);
        else cancelPendingAction(lastChatItem.id);
        return;
      }
    }
    const gameQnaCommand = currentChat === "Game Q&A" ? resolveChatCommand(request) : null;
    if (currentChat === "Game Q&A") {
      if (gameQnaCommand?.kind === "help") {
        setShowCommandHelp(true);
        return;
      }
      const storyReviewMatch = request.match(/^(?:스토리\s*검토(?:해줘|해 줘)?|\/story-review)(?:\s+([\s\S]+))?$/i);
      if (storyReviewMatch) {
        const draftContent = storyReviewMatch[1]?.trim() ?? "";
        recordGameQnaWork(request, "검토 대기");
        window.dispatchEvent(new CustomEvent("game-qna-story-review", { detail: { content: draftContent } }));
        setChat((items) => [...items, { id: `message-${Date.now()}`, kind: "text", text: `You: ${request}` }, { id: `review-${Date.now()}`, kind: "text", text: "Story Review Workspace로 이동했습니다. 초안을 입력하고 검토를 실행하세요." }]);
        persistMessage("user", request);
        persistMessage("assistant", "Story Review Workspace로 이동했습니다. 초안을 입력하고 검토를 실행하세요.");
        return;
      }
    }
    const requestedAgent = gameQnaCommand?.kind === "request" && gameQnaCommand.command
      ? null
      : routeAgentRequest(request);
    if (requestedAgent && requestedAgent !== currentChat) {
      activateChatTask(requestedAgent);
      activeChatRef.current = requestedAgent;
      setActiveSection("Home");
      setActiveChat(requestedAgent);
      setMessage(request);
      return;
    }
    const responseChat = activeSection === "Today Briefing" && !activeChat ? routeBriefingRequest(request) : currentChat;
    if (responseChat !== currentChat) { activeChatRef.current = responseChat; setActiveSection("Home"); setActiveChat(responseChat); }
    startChatTask(responseChat);
    if (responseChat === "Game Q&A") recordGameQnaWork(request, "진행 중");
    setChat((items) => [...items, { id: `message-${Date.now()}`, kind: "text", text: `You: ${request}` }]);
    persistMessage("user", request);
    if (getTaskAction(request) === "confirm") {
      const proposal = createTaskProposal(request, `proposal-${Date.now()}`);
      if (!proposal) return;
      const question = "이 내용을 Project Task로 추가할까요? 아래 내용을 확인해 주세요.";
      setChat((items) => [...items, { id: `question-${Date.now()}`, kind: "text", text: question }, { id: proposal.id, kind: "proposal", proposal, state: "pending" }]);
      persistMessage("assistant", question);
      return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: request, owner: assigneeName }),
      });
      if (!response.ok) {
        let detail = `Agent reply failed (${response.status})`;
        try {
          const errorData = await response.json() as { detail?: string };
          if (errorData.detail) detail = errorData.detail;
        } catch {
          // Keep the HTTP status when the server does not return JSON.
        }
        throw new Error(detail);
      }
      const data = await response.json() as { answer?: string; taskId?: string; unresolvedScenes?: RawUnresolvedScene[]; pending_action?: { skill_id?: string; arguments?: Record<string, unknown> } | null };
      const rawReply = data.answer || createChatReply(request);
      const artPrompt = responseChat === "Game Q&A" ? extractArtPrompt(rawReply) : null;
      const reply = artPrompt ? formatArtPromptForChat(artPrompt) : rawReply;
      if (artPrompt) {
        setPendingArtPrompt(artPrompt);
        setArtPromptTransferStatus("idle");
        window.localStorage.setItem("game-qna-art-prompt", JSON.stringify(artPrompt));
      }
      // `assistant_ask`가 확인이 필요한 동작을 골랐으면(예: analyze_meeting) 텍스트
      // 답 뒤에 확인/취소 카드를 이어 붙인다 — "확인"을 누르면 원래 요청 문장(`request`)
      // 을 `confirmed_skill_id`/`confirmed_arguments`와 함께 그대로 재전송한다. 이
      // `pending_action`을 `reply`와 같은 저장 메시지에 함께 실어 보내야, 탭 전환·새로고침
      // 뒤에도 `rebuildChatFromHistory()`가 이 카드를 되살릴 수 있다.
      const normalizedPendingAction: PendingAction | null = data.pending_action?.skill_id
        ? { skill_id: data.pending_action.skill_id, arguments: data.pending_action.arguments ?? {} }
        : null;
      persistMessage("assistant", reply, normalizedPendingAction);
      if (!shouldApplyChatResponse(activeChatRef.current, responseChat)) return;
      const textMessage: ChatMessage = { id: `response-${Date.now()}`, kind: "text", text: reply };
      const pendingActionMessage: ChatMessage | null = normalizedPendingAction
        ? { id: `pending-action-${Date.now()}`, kind: "pending-action", action: normalizedPendingAction, chatName: responseChat, text: request, state: "pending" }
        : null;
      if (data.taskId && data.unresolvedScenes?.length) {
        setChat((items) => [...items, textMessage, { id: `unresolved-${Date.now()}`, kind: "unresolved-scenes", taskId: data.taskId!, scenes: buildUnresolvedScenes(data.unresolvedScenes!) }]);
      } else if (pendingActionMessage) {
        setChat((items) => [...items, textMessage, pendingActionMessage]);
      } else {
        setChat((items) => [...items, textMessage]);
      }
      completeChatTask(responseChat);
      if (responseChat === "Game Q&A") recordGameQnaWork(request, "완료");
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unknown agent error";
      const reply = `Main Agent 오류: ${detail}`;
      persistMessage("assistant", reply);
      if (!shouldApplyChatResponse(activeChatRef.current, responseChat)) return;
      setChat((items) => [...items, { id: `error-${Date.now()}`, kind: "text", text: reply }]);
      if (responseChat === "Game Q&A") recordGameQnaWork(request, "오류");
    }
  }

  function renderChatMessage(item: ChatMessage) {
    if (item.kind === "text") return <p className="chat-answer" key={item.id}>{item.text}</p>;
    if (item.kind === "pending-action") return <div className={`proposal-card ${item.state}`} key={item.id}><strong>실행 확인 필요</strong><div className="proposal-row"><span>Skill</span><b>{item.action.skill_id}</b></div>{item.state === "pending" && <div className="proposal-actions"><button type="button" className="save-task" onClick={() => void confirmPendingAction(item.id)}>확인</button><button type="button" className="cancel-task" onClick={() => cancelPendingAction(item.id)}>취소</button></div>}{item.state === "confirming" && <small>실행 중...</small>}{item.state === "done" && <small className="proposal-success">실행 완료.</small>}{item.state === "cancelled" && <small>요청을 취소했습니다.</small>}{item.state === "error" && <small className="proposal-error">실행에 실패했습니다. 다시 시도해 주세요.</small>}</div>;
    if (item.kind === "unresolved-scenes") return <div className="proposal-card unresolved-scenes-card" key={item.id}><strong>수동 수정이 필요한 장면</strong>{item.scenes.map((scene) => <div className="unresolved-scene-row" key={scene.sceneId}><img className="unresolved-scene-thumb" src={scene.imageUrl} alt={scene.sceneId} /><div className="unresolved-scene-info"><b>{scene.sceneId}</b><ul>{scene.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>{scene.status === "pending" && <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadSceneFix(item.id, item.taskId, scene.sceneId, file); event.target.value = ""; }} />}{scene.status === "uploading" && <small>업로드 중...</small>}{scene.status === "error" && <small className="unresolved-scene-error">업로드 실패. 다시 시도해 주세요.</small>}</div></div>)}</div>;
    return <div className={`proposal-card ${item.state}`} key={item.id}><strong>Task proposal</strong><div className="proposal-row"><span>Task</span><b>{item.proposal.name}</b></div><div className="proposal-row"><span>Owner</span><b>{item.proposal.owner}</b></div><div className="proposal-row"><span>Status</span><b>{item.proposal.status}</b></div><div className="proposal-row"><span>Agent</span><b>{item.proposal.agent}</b></div>{item.state === "pending" && <div className="proposal-actions"><button type="button" className="save-task" onClick={() => confirmProposal(item.id)}>Add Task</button><button type="button" className="cancel-task" onClick={() => cancelProposal(item.id)}>Cancel</button></div>}{item.state === "adding" && <small>Adding task...</small>}{item.state === "added" && <small className="proposal-success">Task added to Project Task.</small>}{item.state === "cancelled" && <small>Task addition cancelled.</small>}{item.state === "error" && <small className="proposal-error">Task could not be added. Check the API connection.</small>}</div>;
  }

  function renderPolicies() {
    return policyView === "company" ? renderCompanyPolicies() : <TaskLogPanel />;
  }

  function renderCompanyPolicies() {
    return <section className="policies-card"><div className="policies-heading"><div><p className="eyebrow">MAIN AGENT / POLICIES / COMPANY</p><h2>사내규정</h2><p>팀에서 함께 지켜야 할 기본 규정과 업무 기준입니다.</p></div><input aria-label="Search company policies" placeholder="규정 검색" /></div><div className="policy-grid"><article><span>01</span><h3>근무 및 휴가</h3><p>근무시간, 휴가, 재택근무 기준</p></article><article><span>02</span><h3>보안 및 개인정보</h3><p>정보보호와 데이터 취급 기준</p></article><article><span>03</span><h3>업무 운영</h3><p>회의, 승인, 협업 운영 기준</p></article><article><span>04</span><h3>복지 및 지원</h3><p>구성원 지원 제도와 이용 안내</p></article></div></section>;
  }

  const referenceReportKind = activeSection === "Today Briefing" ? "briefing" : activeSection === "Weekly Report" ? "weekly" : null;

  return <div className={`shell legacy-ui ${activeChat ? "chat-active agent-content-updated" : "section-active"}`} data-active-chat={currentChat} data-active-section={activeSection}><UpdatedReportNav variant="legacy" activeSection={activeSection} activeChat={activeChat} onSelect={handleSectionClick} /><TaskQuickActions variant="updated" currentChat={activeChat} onSelect={selectQuickAction} assigneeName={assigneeName} onRecordingChange={setIsRecordingMeeting} />{activeChat === "Video Generation" && <div className="video-agent-host"><VideoAgentPage initialBrief={message} owner={assigneeName} /></div>}{activeSection === "Today Briefing" && !activeChat && <><ReferenceBriefingPanel kind="briefing" assigneeName={assigneeName} /><button className="report-confirm-button report-confirm-floating" type="button" onClick={confirmReport}>확인 완료</button></>}{activeSection === "Weekly Report" && !activeChat && <><WeeklyReportPanel assigneeName={assigneeName} /><button className="report-confirm-button report-confirm-floating" type="button" onClick={confirmReport}>확인 완료</button></>}
    <aside className="sidebar"><h2>WorkMate AI</h2><button className="create" type="button">+ Create</button>{legacySections.map((item) => item === "Policies" ? <div key={item}><button className={`nav works-toggle ${activeSection === "Company Policies" || activeSection === "Operational Policies" ? "active" : ""}`} type="button" aria-expanded={policiesOpen} onClick={() => setPoliciesOpen((open) => !open)}>◇ Policies <span>{policiesOpen ? "▾" : "▸"}</span></button>{policiesOpen && <div className="nested-links policy-links"><button className={`nested-link ${activeSection === "Company Policies" ? "active" : ""}`} type="button" onClick={() => { setActiveSection("Company Policies"); setActiveChat(null); }}>사내규정</button><button className={`nested-link ${activeSection === "Operational Policies" ? "active" : ""}`} type="button" onClick={() => { setActiveSection("Operational Policies"); setActiveChat(null); }}>운영 원칙(Task 기록)</button></div>}</div> : <button className={`nav ${activeSection === item && !activeChat ? "active" : ""}`} type="button" aria-pressed={activeSection === item && !activeChat} onClick={() => handleSectionClick(item)} key={item}>◇ {item === "Today Briefing" ? "오늘 브리핑" : item === "Weekly Report" ? "주간 업무보고" : item}</button>)}<><button className="nav works-toggle" type="button" aria-expanded={worksOpen} onClick={() => setWorksOpen((open) => !open)}>◇ Works <span>{worksOpen ? "▾" : "▸"}</span></button>{worksOpen && <div className="nested-links">{chats.map((item) => <button className={`nested-link ${activeChat === item ? "active" : ""}`} type="button" onClick={() => handleChatClick(item)} key={item}>{item}</button>)}</div>}<hr /><button className="section-toggle" type="button" aria-expanded={aiChatsOpen} onClick={() => setAiChatsOpen((open) => !open)}><small>Agent Work</small><span>{aiChatsOpen ? "▾" : "▸"}</span></button>{aiChatsOpen && <div className="nested-links task-links">{chatTasks.filter((task) => !task.hidden).map((task) => <div className="nested-task-row" key={task.id}><button className="nested-task" type="button" onClick={() => handleChatClick(task.chat)}><span className={task.status === "working" ? "task-working-dot" : "task-done-space"}>{task.status === "working" ? "○" : ""}</span>{task.title}</button><button className="nested-task-delete" type="button" aria-label={`${task.title} 삭제`} onClick={() => hideChatTask(task.id)}>×</button></div>)}</div>}</> <AssigneeSwitcher name={assigneeName} onChange={changeAssignee} assignments={assignments} onSaveAssignments={saveAssignments} /></aside>
    {activeChat !== "Video Generation" && <><main className="workspace">{activeSection === "Policies" && !activeChat ? renderPolicies() : activeChat === "Development Assistant" ? <><div className="title-row"><div><p className="eyebrow">MAIN AGENT / {activeChat ?? activeSection.toUpperCase()}</p><h1>Project Demonstration</h1></div><span className="live">● 4 Agents connected</span></div><PreviewPanel currentChat={currentChat} recentGameQnaWork={recentGameQnaWork} artPrompt={pendingArtPrompt} artPromptTransferStatus={artPromptTransferStatus} onSendArtPromptToVideo={() => void sendArtPromptToVideo()} /></> : <><div className="title-row"><div><p className="eyebrow">MAIN AGENT / {activeChat ?? activeSection.toUpperCase()}</p><h1>Project Demonstration</h1></div><span className="live">● 4 Agents connected</span></div><section className="table-card"><div className="table-head"><span>Task</span><span>Owner</span><span>Status</span><span>Agent</span></div>{tasks.map((task) => editingTaskId === task.id && draftTask ? <div className="task-row task-edit-row" key={task.id}><span>{task.name}</span><input value={draftTask.owner} onChange={(event) => setDraftTask({ ...draftTask, owner: event.target.value })} aria-label="Owner" placeholder="Owner" /><select value={draftTask.status} onChange={(event) => setDraftTask({ ...draftTask, status: event.target.value })} aria-label="Status">{statuses.map((status) => <option key={status}>{status}</option>)}</select><div className="edit-actions"><select value={draftTask.agent} onChange={(event) => setDraftTask({ ...draftTask, agent: event.target.value })} aria-label="Agent">{chats.map((agent) => <option key={agent}>{agent}</option>)}</select><button className="save-task" type="button" onClick={commitEdit} onMouseDown={commitEdit}>Save</button><button className="cancel-task" type="button" onClick={cancelEdit} onMouseDown={cancelEdit}>Cancel</button></div></div> : <div className="task-row" key={task.id}><span>□&nbsp;{task.name}</span><span className="owner">{task.owner || "○"}</span><span><b className={`status ${task.status.toLowerCase().replaceAll(" ", "-")}`}>{task.status}</b></span><span className="agent-actions"><button className="agent-button" type="button">{task.agent} ↗</button><button className="edit-task" type="button" onClick={() => startEdit(task)}>Edit</button></span></div>)}{isAddingTask && <form className="task-form" onSubmit={addTask}><input autoFocus value={newTaskName} onChange={(event) => setNewTaskName(event.target.value)} placeholder="Task name" aria-label="Task name" /><select value={newTaskAgent} onChange={(event) => setNewTaskAgent(event.target.value)} aria-label="Task agent">{chats.map((agent) => <option key={agent}>{agent}</option>)}</select><button className="save-task" type="submit">Add</button><button className="cancel-task" type="button" onClick={() => setIsAddingTask(false)}>Cancel</button></form>}<button className="add-task" type="button" onClick={() => setIsAddingTask(true)}>+ Add task</button></section><PreviewPanel currentChat={currentChat} recentGameQnaWork={recentGameQnaWork} artPrompt={pendingArtPrompt} artPromptTransferStatus={artPromptTransferStatus} onSendArtPromptToVideo={() => void sendArtPromptToVideo()} /></>}</main>
    <aside className="chat-panel"><h3>AI Chat · {currentChat}<button className="reset-chat" type="button" onClick={() => void resetChat()}>Reset chat</button>{currentChat === "Game Q&A" && <button className="story-toggle" type="button" onClick={() => setIsStoryFormOpen((value) => !value)}>{isStoryFormOpen ? "Close" : "+ Add story"}</button>}</h3>{currentChat === "Game Q&A" && isStoryFormOpen && <form className="story-form" onSubmit={addStory}><input value={storyName} onChange={(event) => setStoryName(event.target.value)} placeholder="Story title" required /><input value={storyKeywords} onChange={(event) => setStoryKeywords(event.target.value)} placeholder="Keywords, comma separated" required /><textarea value={storyAnswer} onChange={(event) => setStoryAnswer(event.target.value)} placeholder="Story content" rows={5} required /><button type="submit">Save story</button>{storyNotice && <small>{storyNotice}</small>}</form>}{currentChat === "Game Q&A" && showCommandHelp && <div className="command-help" role="dialog" aria-label="Game Q&A commands"><div className="command-help-heading"><strong>Game Q&A 명령어</strong><button type="button" className="command-help-close" onClick={() => setShowCommandHelp(false)}>닫기</button></div>{commandCatalog.map((item) => <button type="button" className="command-item" key={item.command} onClick={() => selectGameQaCommand(item.command)}><strong>{item.command}</strong><span>{item.label} · {item.description}</span></button>)}</div>}<div className="messages" ref={messagesRef}>{chat.length ? chat.map(renderChatMessage) : <div className="empty">Type a message to start a conversation</div>}</div><form className="composer" onSubmit={submit}><input value={message} onChange={(event) => { setMessage(event.target.value); if (currentChat === "Game Q&A" && (event.target.value === "/" || event.target.value.startsWith("/?") || event.target.value.startsWith("/help"))) setShowCommandHelp(true); }} onKeyDown={(event) => { if (event.key === "Escape") setShowCommandHelp(false); }} placeholder={currentChat === "Game Q&A" ? "Type /? for Game Q&A commands..." : "Type a message..."} /><button type="submit">➤</button></form></aside></>}
  </div>;
}


