import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { getLanguageLabel, getPreviewKind, PreviewKind } from "./preview-utils";
import { buildStoryDraft, canApproveStory, reviewLabel, type StoryDraft, type StoryReview } from "./story-review-utils";
import { normalizeStoryReviewInput, parseStoryText, storyEditorText } from "./story-import";
import { shouldShowCodePreview } from "./preview-mode";
import GameQnaSummary from "./GameQnaSummary";
import type { RecentGameQnaWork } from "./game-qna-summary-utils";
import type { ArtPrompt } from "./art-prompt-utils";
import { getKnowledgeInputStatus } from "./knowledge-input-status";

const API_BASE_URL = "http://127.0.0.1:8000";
const DEV_AGENT_DASHBOARD_URL = "http://localhost:8004";
type PreviewFile = { id: string; file: File; kind: PreviewKind; content?: string; objectUrl?: string; error?: string };

function createPreviewFile(file: File): PreviewFile {
  const kind = getPreviewKind(file.name);
  return { id: `${file.name}-${file.lastModified}-${file.size}`, file, kind, objectUrl: kind === "image" ? URL.createObjectURL(file) : undefined };
}

type PreviewPanelProps = { isGameQa?: boolean; recentGameQnaWork?: RecentGameQnaWork[]; artPrompt?: ArtPrompt | null; artPromptTransferStatus?: "idle" | "sending" | "sent" | "error"; onSendArtPromptToVideo?: () => void };

export default function PreviewPanel({ isGameQa, recentGameQnaWork, artPrompt, artPromptTransferStatus, onSendArtPromptToVideo }: PreviewPanelProps) {
  const [activeChat, setActiveChat] = useState(() => document.querySelector(".shell")?.getAttribute("data-active-chat") ?? "");
  const [isOpen, setIsOpen] = useState(false);
  const [files, setFiles] = useState<PreviewFile[]>([]);
  const [activeId, setActiveId] = useState<string>();
  const [storyChat, setStoryChat] = useState("");
  const [storyDraft, setStoryDraft] = useState<StoryDraft | null>(null);
  const [storyReview, setStoryReview] = useState<StoryReview | null>(null);
  const [storyNotice, setStoryNotice] = useState("");
  const [isReviewingStory, setIsReviewingStory] = useState(false);
  const filesRef = useRef<PreviewFile[]>([]);
  const activeFile = useMemo(() => files.find((item) => item.id === activeId) ?? files[0], [activeId, files]);

  useEffect(() => { filesRef.current = files; }, [files]);
  useEffect(() => () => filesRef.current.forEach((item) => item.objectUrl && URL.revokeObjectURL(item.objectUrl)), []);
  useEffect(() => {
    const shell = document.querySelector(".shell");
    if (!shell) return undefined;
    const observer = new MutationObserver(() => setActiveChat(shell.getAttribute("data-active-chat") ?? ""));
    observer.observe(shell, { attributes: true, attributeFilter: ["data-active-chat"] });
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    function handleStoryReviewRoute(event: Event) {
      const content = (event as CustomEvent<{ content?: string }>).detail?.content ?? "";
      setStoryChat(content);
      window.setTimeout(() => {
        document.querySelector(".story-workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
        document.querySelector<HTMLTextAreaElement>(".story-chat textarea")?.focus();
      }, 0);
    }
    window.addEventListener("game-qna-story-review", handleStoryReviewRoute);
    return () => window.removeEventListener("game-qna-story-review", handleStoryReviewRoute);
  }, []);

  const showStoryWorkspace = isGameQa ?? activeChat === "Game Q&A";
  const knowledgeInputStatus = getKnowledgeInputStatus({ hasDraft: Boolean(storyDraft), isReviewing: isReviewingStory, review: storyReview, notice: storyNotice });

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    if (!selected.length) return;
    const loadedFiles = await Promise.all(selected.map(async (file) => {
      const item = createPreviewFile(file);
      if (item.kind !== "code") return item;
      try { return { ...item, content: await file.text() }; }
      catch { return { ...item, error: "File content could not be read." }; }
    }));
    setFiles((current) => [...current, ...loadedFiles.filter((item) => !current.some((existing) => existing.id === item.id))]);
    setActiveId(loadedFiles[0]?.id);
    setIsOpen(true);
    event.target.value = "";
  }

  async function reviewStory(draft: StoryDraft) {
    setStoryNotice("");
    setIsReviewingStory(true);
    setStoryDraft(draft);
    setStoryReview(null);
    window.dispatchEvent(new CustomEvent("game-qna-story-review-state", { detail: { status: "working" } }));
    try {
      const response = await fetch(`${API_BASE_URL}/api/stories/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      if (!response.ok) throw new Error("Story review API failed");
      const review = await response.json() as StoryReview;
      setStoryReview(review);
      setStoryNotice(`Review complete: ${reviewLabel(review)}.`);
      window.dispatchEvent(new CustomEvent("game-qna-story-review-state", { detail: { status: "done" } }));
      window.setTimeout(() => document.querySelector(".story-review-card")?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
    } catch {
      setStoryNotice("Story could not be reviewed. Check the Catalog connection.");
      window.dispatchEvent(new CustomEvent("game-qna-story-review-state", { detail: { status: "error" } }));
    } finally {
      setIsReviewingStory(false);
    }
  }

  async function submitStoryChat(event: FormEvent) {
    event.preventDefault();
    if (!storyChat.trim()) return;
    const parsed = normalizeStoryReviewInput(storyChat, "chat-story.txt");
    if (!parsed.answer) {
      setStoryNotice("Write story content before requesting a review.");
      return;
    }
    await reviewStory(buildStoryDraft(parsed.name, parsed.keywords.length ? parsed.keywords.join(", ") : parsed.name, parsed.answer));
  }

  async function handleStoryTxt(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const rawText = await file.text();
      const parsed = parseStoryText(rawText, file.name);
      setStoryChat(storyEditorText(rawText));
      if (!parsed.answer) {
        setStoryNotice("The TXT file does not contain story content.");
        return;
      }
      await reviewStory(buildStoryDraft(parsed.name, parsed.keywords.length ? parsed.keywords.join(", ") : parsed.name, parsed.answer));
    } catch {
      setStoryNotice("The TXT file could not be read.");
    }
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
      setStoryChat("");
      setStoryDraft(null);
      setStoryReview(null);
      setStoryNotice("Story approved and saved to Catalog.");
    } catch {
      setStoryNotice("Story could not be saved. Review may have expired.");
    }
  }

  return <>
    {showStoryWorkspace && <GameQnaSummary storyReview={storyReview} storyNotice={storyNotice} knowledgeInputStatus={knowledgeInputStatus} chatWorks={recentGameQnaWork} artPrompt={artPrompt} artPromptTransferStatus={artPromptTransferStatus} onSendArtPromptToVideo={onSendArtPromptToVideo} />}
    {shouldShowCodePreview(showStoryWorkspace) && activeChat === "Video Generation" && <section className={`preview-panel ${isOpen ? "is-open" : "is-closed"}`}>
      <div className="preview-header"><div><span className="preview-kicker">ADD CODE</span><h2>Workspace Preview</h2></div><div className="preview-actions"><label className="file-button">+ Add file<input type="file" multiple onChange={handleFiles} accept=".png,.jpg,.jpeg,.gif,.webp,.js,.jsx,.ts,.tsx,.py,.java,.cs,.cpp,.c,.go,.rs,.json,.yaml,.yml,.md,.html,.css,.scss,.sql,.sh" /></label><button className="collapse-button" type="button" onClick={() => setIsOpen((value) => !value)} aria-expanded={isOpen}>{isOpen ? "Collapse" : "Open"}</button></div></div>
      {isOpen && <div className="preview-body"><div className="preview-toolbar"><div className="file-tabs" role="list" aria-label="Select file">{files.map((item) => <button className={`file-tab ${activeFile?.id === item.id ? "active" : ""}`} key={item.id} type="button" onClick={() => setActiveId(item.id)}>{item.file.name}</button>)}</div><div className="view-tabs" aria-label="Preview format"><span className={`view-tab ${activeFile?.kind === "image" ? "active" : ""}`}>Image</span><span className={`view-tab ${activeFile?.kind === "code" ? "active" : ""}`}>Code</span></div></div><div className="preview-canvas">{!activeFile && <div className="preview-empty"><strong>Add a file to preview</strong><span>Select an image or code file to inspect it here.</span></div>}{activeFile?.kind === "image" && activeFile.objectUrl && <img className="image-preview" src={activeFile.objectUrl} alt={activeFile.file.name} />}{activeFile?.kind === "code" && <div className="code-preview"><div className="code-meta">{activeFile.file.name}<span>{getLanguageLabel(activeFile.file.name)}</span></div><pre>{activeFile.error ?? activeFile.content ?? "Reading file..."}</pre></div>}{activeFile?.kind === "unsupported" && <div className="preview-empty"><strong>Preview is not supported</strong><span>Select an image or code file.</span></div>}</div></div>}
    </section>}
    {activeChat === "Development Assistant" && <section className="preview-panel is-open">
      <div className="preview-header"><div><span className="preview-kicker">DEV AGENT</span><h2>GitHub Dashboard</h2></div></div>
      <div className="preview-body"><iframe src={DEV_AGENT_DASHBOARD_URL} title="dev-agent GitHub dashboard" style={{ width: "100%", height: "70vh", border: 0, borderRadius: 8 }} /></div>
    </section>}
    {showStoryWorkspace && <section className="story-workspace" aria-label="Game Q&A story workspace">
      <div className="story-workspace-header"><div><span className="preview-kicker">ADD STORY</span><h2>Story Review Workspace</h2></div><label className="file-button">Upload TXT<input type="file" accept=".txt,text/plain" onChange={(event) => void handleStoryTxt(event)} /></label></div>
      <p className="story-help">Chat or upload a TXT file. The RPG story review must pass before it can be added to Catalog.</p>
      <form className="story-chat" onSubmit={submitStoryChat}><textarea value={storyChat} onChange={(event) => { setStoryChat(event.target.value); setStoryDraft(null); setStoryReview(null); setStoryNotice(""); }} placeholder="Describe a story, or paste TXT content here..." rows={5} aria-label="Story chat input" /><button type="submit" disabled={isReviewingStory}>{isReviewingStory ? "Reviewing..." : "Review story"}</button></form>
      {storyDraft && <div className="story-draft"><strong>{storyDraft.name}</strong><span>{storyDraft.keywords.length ? storyDraft.keywords.join(" · ") : "No keywords detected"}</span><p>{storyDraft.answer}</p></div>}
      {storyReview && <div className={`story-review-card ${storyReview.verdict}`}><div className="story-review-heading"><strong>RPG Story Review</strong><b>{reviewLabel(storyReview)}</b></div>{[...[storyReview.continuityConflicts ?? []].map((item) => `Continuity: ${item}`), ...(storyReview.timelineIssues ?? []).map((item) => `Timeline: ${item}`), ...(storyReview.characterConsistency ?? []).map((item) => `Character: ${item}`), ...(storyReview.factionConsistency ?? []).map((item) => `Faction: ${item}`), ...(storyReview.missingRelationships ?? []).map((item) => `Relationship: ${item}`), ...(storyReview.suggestions ?? []).map((item) => `Suggestion: ${item}`)].map((item, index) => <div className="story-review-item" key={`${item}-${index}`}>{item}</div>)}{canApproveStory(storyReview) && <button type="button" className="save-task" onClick={() => void approveStory()}>Add Story to Catalog</button>}</div>}
      {storyNotice && <small className="story-notice">{storyNotice}</small>}
    </section>}
  </>;
}
