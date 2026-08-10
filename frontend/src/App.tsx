import { FormEvent, useEffect, useRef, useState } from "react";
import PreviewPanel from "./PreviewPanel";
import "./chat-answer.css";
import { selectMenu } from "./menu-utils";
import { createChatReply, createTask, createTaskProposal, getTaskAction, mapTaskStatus, pollTask, shouldApplyChatResponse, updateTask } from "./task-utils";
import "./task-form.css";
import { commandCatalog, resolveChatCommand } from "./command-utils";
import { scrollChatToBottom } from "./chat-scroll";
import { buildStoryDraft, canApproveStory, reviewLabel, type StoryDraft, type StoryReview } from "./story-review-utils";

const API_BASE_URL = "http://127.0.0.1:8000";
type Task = { id: string; name: string; owner: string; status: string; agent: string };
type ChatMessage = { id: string; kind: "text"; text: string } | { id: string; kind: "proposal"; proposal: Task; state: "pending" | "adding" | "added" | "cancelled" | "error" };
type StoredMessage = { id: string; role: "user" | "assistant" | "system"; content: string };
const sections = ["Home", "Roles", "Skills", "Meetings", "My Tasks", "More"];
const chats = ["Workmate AI", "Video Generation", "Development Assistant", "Game Q&A"];
const statuses = ["Ready to start", "In Progress", "Done", "Stuck", "Waiting for review"];
const initialTasks: Task[] = [
  { id: "1", name: "게임 Q&A 지식 검색", owner: "PW", status: "Done", agent: "Game Q&A" },
  { id: "2", name: "영상 기획 초안 생성", owner: "T", status: "In Progress", agent: "Video Generation" },
  { id: "3", name: "PR 변경사항 검토", owner: "", status: "Ready to start", agent: "Development Assistant" },
];

export default function App() {
  const [tasks, setTasks] = useState(initialTasks);
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [chatSessions, setChatSessions] = useState<Record<string, string>>({});
  const [activeSection, setActiveSection] = useState("Home");
  const [activeChat, setActiveChat] = useState<string | null>("Workmate AI");
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
  const currentSessionId = chatSessions[currentChat];
  const activeChatRef = useRef(currentChat);
  const messagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollChatToBottom(messagesRef.current);
  }, [chat, currentChat]);

  useEffect(() => {
    activeChatRef.current = currentChat;
    let cancelled = false;
    setChat([]);
    fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/session`)
      .then((response) => response.ok ? response.json() as Promise<{ session_id: string; messages: StoredMessage[] }> : Promise.reject(new Error("Chat history failed")))
      .then((session) => { if (!cancelled) { setChatSessions((items) => ({ ...items, [currentChat]: session.session_id })); setChat(session.messages.map((item) => ({ id: item.id, kind: "text", text: item.role === "user" ? `You: ${item.content}` : item.content }))); } })
      .catch(() => { if (!cancelled) setChat([]); });
    return () => { cancelled = true; };
  }, [currentChat]);

  function persistMessage(role: "user" | "assistant", content: string) {
    void fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role, content, session_id: currentSessionId }) }).catch(() => undefined);
  }

  async function resetChat() {
    const response = await fetch(`${API_BASE_URL}/api/chats/${encodeURIComponent(currentChat)}/reset`, { method: "POST" });
    if (!response.ok) return;
    const data = await response.json() as { session_id: string };
    setChatSessions((items) => ({ ...items, [currentChat]: data.session_id }));
    setChat([]);
  }

  function handleSectionClick(section: string) { const state = selectMenu({ type: "section", id: section }); activeChatRef.current = state.activeChat ?? "Workmate AI"; setActiveSection(state.activeSection); setActiveChat(state.activeChat); }
  function handleChatClick(chatName: string) { const state = selectMenu({ type: "chat", id: chatName }, activeSection); activeChatRef.current = state.activeChat ?? "Workmate AI"; setActiveSection(state.activeSection); setActiveChat(state.activeChat); }
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
        body: JSON.stringify(draft),
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

  function selectGameQaCommand(command: string) {
    const resolved = resolveChatCommand(command);
    if (resolved.kind !== "request") return;
    setMessage(`${resolved.command} ${resolved.content}`);
    setShowCommandHelp(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); if (!message.trim()) return;
    const request = message.trim(); setMessage("");
    if (currentChat === "Game Q&A") {
      const resolved = resolveChatCommand(request);
      if (resolved.kind === "help") {
        setShowCommandHelp(true);
        return;
      }
    }
    const responseChat = currentChat;
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
        body: JSON.stringify({ content: request }),
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
      const data = await response.json() as { answer?: string };
      const reply = data.answer || createChatReply(request);
      persistMessage("assistant", reply);
      if (!shouldApplyChatResponse(activeChatRef.current, responseChat)) return;
      setChat((items) => [...items, { id: `response-${Date.now()}`, kind: "text", text: reply }]);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unknown agent error";
      const reply = `Main Agent 오류: ${detail}`;
      persistMessage("assistant", reply);
      if (!shouldApplyChatResponse(activeChatRef.current, responseChat)) return;
      setChat((items) => [...items, { id: `error-${Date.now()}`, kind: "text", text: reply }]);
    }
  }

  function renderChatMessage(item: ChatMessage) {
    if (item.kind === "text") return <p className="chat-answer" key={item.id}>{item.text}</p>;
    return <div className={`proposal-card ${item.state}`} key={item.id}><strong>Task proposal</strong><div className="proposal-row"><span>Task</span><b>{item.proposal.name}</b></div><div className="proposal-row"><span>Owner</span><b>{item.proposal.owner}</b></div><div className="proposal-row"><span>Status</span><b>{item.proposal.status}</b></div><div className="proposal-row"><span>Agent</span><b>{item.proposal.agent}</b></div>{item.state === "pending" && <div className="proposal-actions"><button type="button" className="save-task" onClick={() => confirmProposal(item.id)}>Add Task</button><button type="button" className="cancel-task" onClick={() => cancelProposal(item.id)}>Cancel</button></div>}{item.state === "adding" && <small>Adding task...</small>}{item.state === "added" && <small className="proposal-success">Task added to Project Task.</small>}{item.state === "cancelled" && <small>Task addition cancelled.</small>}{item.state === "error" && <small className="proposal-error">Task could not be added. Check the API connection.</small>}</div>;
  }

  return <div className="shell">
    <aside className="sidebar"><h2>WorkMate AI</h2><button className="create" type="button">+ Create</button>{sections.map((item) => <button className={`nav ${activeSection === item && !activeChat ? "active" : ""}`} type="button" aria-pressed={activeSection === item && !activeChat} onClick={() => handleSectionClick(item)} key={item}>◇ {item}</button>)}<hr /><small>AI Chats</small>{chats.map((item) => <button className={`chat-link ${activeChat === item ? "active" : ""}`} type="button" aria-pressed={activeChat === item} onClick={() => handleChatClick(item)} key={item}>{item}</button>)}<div className="space">Spaces <span>+</span></div><button className="chat-link" type="button" onClick={() => handleChatClick("General")}>◇ General</button></aside>
    <main className="workspace"><div className="title-row"><div><p className="eyebrow">MAIN AGENT / {activeChat ?? activeSection.toUpperCase()}</p><h1>PROJECT_DEMO</h1></div><span className="live">● 4 Agents connected</span></div><section className="table-card"><div className="table-head"><span>Task</span><span>Owner</span><span>Status</span><span>Agent</span></div>{tasks.map((task) => editingTaskId === task.id && draftTask ? <div className="task-row task-edit-row" key={task.id}><span>{task.name}</span><input value={draftTask.owner} onChange={(event) => setDraftTask({ ...draftTask, owner: event.target.value })} aria-label="Owner" placeholder="Owner" /><select value={draftTask.status} onChange={(event) => setDraftTask({ ...draftTask, status: event.target.value })} aria-label="Status">{statuses.map((status) => <option key={status}>{status}</option>)}</select><div className="edit-actions"><select value={draftTask.agent} onChange={(event) => setDraftTask({ ...draftTask, agent: event.target.value })} aria-label="Agent">{chats.map((agent) => <option key={agent}>{agent}</option>)}</select><button className="save-task" type="button" onClick={commitEdit} onMouseDown={commitEdit}>Save</button><button className="cancel-task" type="button" onClick={cancelEdit} onMouseDown={cancelEdit}>Cancel</button></div></div> : <div className="task-row" key={task.id}><span>□&nbsp;{task.name}</span><span className="owner">{task.owner || "○"}</span><span><b className={`status ${task.status.toLowerCase().replaceAll(" ", "-")}`}>{task.status}</b></span><span className="agent-actions"><button className="agent-button" type="button">{task.agent} ↗</button><button className="edit-task" type="button" onClick={() => startEdit(task)}>Edit</button></span></div>)}{isAddingTask && <form className="task-form" onSubmit={addTask}><input autoFocus value={newTaskName} onChange={(event) => setNewTaskName(event.target.value)} placeholder="Task name" aria-label="Task name" /><select value={newTaskAgent} onChange={(event) => setNewTaskAgent(event.target.value)} aria-label="Task agent">{chats.map((agent) => <option key={agent}>{agent}</option>)}</select><button className="save-task" type="submit">Add</button><button className="cancel-task" type="button" onClick={() => setIsAddingTask(false)}>Cancel</button></form>}<button className="add-task" type="button" onClick={() => setIsAddingTask(true)}>+ Add task</button></section><PreviewPanel /></main>
    <aside className="chat-panel"><h3>AI Chat · {currentChat}<button className="reset-chat" type="button" onClick={() => void resetChat()}>Reset chat</button>{currentChat === "Game Q&A" && <button className="story-toggle" type="button" onClick={() => setIsStoryFormOpen((value) => !value)}>{isStoryFormOpen ? "Close" : "+ Add story"}</button>}</h3>{currentChat === "Game Q&A" && isStoryFormOpen && <form className="story-form" onSubmit={addStory}><input value={storyName} onChange={(event) => setStoryName(event.target.value)} placeholder="Story title" required /><input value={storyKeywords} onChange={(event) => setStoryKeywords(event.target.value)} placeholder="Keywords, comma separated" required /><textarea value={storyAnswer} onChange={(event) => setStoryAnswer(event.target.value)} placeholder="Story content" rows={5} required /><button type="submit">Save story</button>{storyNotice && <small>{storyNotice}</small>}</form>}{currentChat === "Game Q&A" && showCommandHelp && <div className="command-help" role="dialog" aria-label="Game Q&A commands"><div className="command-help-heading"><strong>Game Q&A 명령어</strong><button type="button" className="command-help-close" onClick={() => setShowCommandHelp(false)}>닫기</button></div>{commandCatalog.map((item) => <button type="button" className="command-item" key={item.command} onClick={() => selectGameQaCommand(item.command)}><strong>{item.command}</strong><span>{item.label} · {item.description}</span></button>)}</div>}<div className="messages" ref={messagesRef}>{chat.length ? chat.map(renderChatMessage) : <div className="empty">Type a message to start a conversation</div>}</div><form className="composer" onSubmit={submit}><input value={message} onChange={(event) => { setMessage(event.target.value); if (currentChat === "Game Q&A" && (event.target.value === "/" || event.target.value.startsWith("/?") || event.target.value.startsWith("/help"))) setShowCommandHelp(true); }} onKeyDown={(event) => { if (event.key === "Escape") setShowCommandHelp(false); }} placeholder={currentChat === "Game Q&A" ? "Type /? for Game Q&A commands..." : "Type a message..."} /><button type="submit">➤</button></form></aside>
  </div>;
}
