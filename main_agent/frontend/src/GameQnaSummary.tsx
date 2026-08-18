import { useEffect, useState } from "react";
import { formatArtPromptJson, parseArtPromptJson, type ArtPrompt } from "./art-prompt-utils";
import { recentGameQnaWork, reviewSummaryLines, type RecentGameQnaWork } from "./game-qna-summary-utils";
import type { KnowledgeInputStatus } from "./knowledge-input-status";

type StoryReview = { verdict?: string; continuityConflicts?: string[]; timelineIssues?: string[]; characterConsistency?: string[]; factionConsistency?: string[]; missingRelationships?: string[]; suggestions?: string[] };
type TransferStatus = "idle" | "sending" | "sent" | "error";
type Props = {
  storyReview: StoryReview | null;
  storyNotice: string;
  knowledgeInputStatus?: KnowledgeInputStatus;
  chatWorks?: RecentGameQnaWork[];
  artPrompt?: ArtPrompt | null;
  artPromptTransferStatus?: TransferStatus;
  onSendArtPromptToVideo?: () => void;
};

function transferCopy(prompt: ArtPrompt | null | undefined, status: TransferStatus): { title: string; detail: string } {
  if (!prompt) return { title: "전송할 프롬프트 없음", detail: "Game Q&A에서 /art 요청을 완료하면 원본 JSON을 보관합니다." };
  if (status === "sending") return { title: "Video 담당자에게 전송 중", detail: "저장된 JSON을 A2A 통신 계약의 message 본문으로 전달하고 있습니다." };
  if (status === "sent") return { title: "Video 담당자 전송 완료", detail: "저장된 JSON이 Video Agent에 전달되었습니다. 수정 후 다시 전송할 수 있습니다." };
  if (status === "error") return { title: "전송 실패", detail: "원본 JSON은 보관되어 있습니다. 내용을 확인한 뒤 다시 전송해 주세요." };
  return { title: "전송 대기", detail: "원본 JSON을 보관했습니다. 확인 또는 수정 후 Video 담당자에게 전달할 수 있습니다." };
}

export default function GameQnaSummary({ storyReview, storyNotice, knowledgeInputStatus = { label: "업로드 대기", progress: 0 }, chatWorks = [], artPrompt = null, artPromptTransferStatus = "idle", onSendArtPromptToVideo }: Props) {
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [draftJson, setDraftJson] = useState("");
  const [editorError, setEditorError] = useState("");
  const [savedPrompt, setSavedPrompt] = useState<ArtPrompt | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setSavedPrompt(null);
  }, [artPrompt]);

  const handoffPrompt = savedPrompt ?? artPrompt;
  const reviewLines = storyReview ? reviewSummaryLines(storyReview) : storyNotice.includes("saved") ? ["최신 스토리가 Catalog에 반영되었습니다."] : reviewSummaryLines(null);
  const fallbackWork = recentGameQnaWork(storyReview, storyNotice);
  const recentWorks = chatWorks.length ? chatWorks : [fallbackWork];
  const latestWork = recentWorks[0];
  const transfer = transferCopy(handoffPrompt, artPromptTransferStatus);

  function openEditor() {
    if (!handoffPrompt) return;
    setDraftJson(formatArtPromptJson(handoffPrompt));
    setEditorError("");
    setIsEditorOpen(true);
  }

  function saveEditedPrompt() {
    const parsed = parseArtPromptJson(draftJson);
    if (!parsed) {
      setEditorError("JSON 객체 형식이 올바르지 않습니다. 쉼표, 따옴표, 괄호를 확인해 주세요.");
      return;
    }
    window.localStorage.setItem("game-qna-art-prompt", JSON.stringify(parsed));
    setSavedPrompt(parsed);
    setEditorError("");
    setIsEditorOpen(false);
  }

  return <section className="game-qna-summary" aria-label="Game Q&A 작업 요약">
    <div className="game-qna-summary-cards">
      <article className="art-prompt-handoff">
        <span>VIDEO HANDOFF</span><strong>{transfer.title}</strong><small>{transfer.detail}</small>
        {handoffPrompt && <div className="art-prompt-handoff-actions">
          <button type="button" onClick={openEditor}>전송 JSON 보기·수정</button>
          <button type="button" onClick={() => { void navigator.clipboard?.writeText(formatArtPromptJson(handoffPrompt)); setCopied(true); }}>{copied ? "복사됨" : "JSON 복사"}</button>
          <button type="button" onClick={onSendArtPromptToVideo} disabled={artPromptTransferStatus === "sending"}>{artPromptTransferStatus === "sending" ? "전송 중..." : artPromptTransferStatus === "sent" ? "다시 전송" : "전송"}</button>
        </div>}
      </article>
      <article><span>TXT 반영</span><strong>확인 필요</strong><small>최근 업로드한 파일의 Catalog 반영 상태</small></article>
      <article className={storyReview?.verdict === "reject" ? "attention" : ""}><span>스토리 검토 핵심</span><strong>{storyReview ? `${reviewLines.length}건 요약` : "검토 대기"}</strong><small>자세한 근거와 전체 결과는 채팅에서 확인</small></article>
      <article><span>최근 작업</span><strong>{latestWork.title}</strong><small>{latestWork.detail}</small></article>
    </div>
    <div className="game-qna-summary-grid">
      <section className="summary-panel txt-status-panel"><div className="summary-panel-heading"><div><span>KNOWLEDGE INPUT</span><h3>TXT 반영 상태</h3></div><b>{knowledgeInputStatus.label}</b></div><p>TXT 파일을 업로드하면 Game Q&A가 검토할 수 있는 지식으로 반영합니다.</p><div className="summary-progress"><i style={{ width: `${knowledgeInputStatus.progress}%` }} /></div><small>업로드 → 검토 → Catalog 반영</small></section>
      <section className="summary-panel"><div className="summary-panel-heading"><div><span>STORY REVIEW</span><h3>스토리 검토 핵심</h3></div><b className={storyReview?.verdict === "reject" ? "attention" : "review"}>{storyReview ? "요약 확인" : "검토 대기"}</b></div><ul className="review-summary-list">{reviewLines.map((line, index) => <li key={`${line}-${index}`}>{line}</li>)}</ul><small>전체 검토 내용은 채팅과 RPG Story Review에서 확인하세요.</small></section>
    </div>
    <section className="summary-panel recent-work-panel"><div className="summary-panel-heading"><div><span>RECENT WORK</span><h3>최근 작업</h3></div><small>최근 3건</small></div><div className="recent-work-list">{recentWorks.map((work, index) => <div className="summary-work-row" key={`${work.title}-${work.detail}-${index}`}><span className={`summary-dot ${work.tone}`} /><div><strong>{work.title}</strong><small>{work.detail}</small></div><b>{work.status}</b></div>)}</div></section>
    {isEditorOpen && <div className="art-prompt-editor-backdrop" role="presentation" onMouseDown={() => setIsEditorOpen(false)}>
      <section className="art-prompt-editor" role="dialog" aria-modal="true" aria-label="Video 전달 JSON 편집" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span>VIDEO HANDOFF</span><h3>전송 JSON 보기·수정</h3></div><button type="button" onClick={() => setIsEditorOpen(false)}>닫기</button></header>
        <p>저장한 JSON 원본이 Video 담당자에게 그대로 전달됩니다.</p>
        <textarea value={draftJson} onChange={(event) => { setDraftJson(event.target.value); setEditorError(""); }} spellCheck={false} aria-label="Video 담당자에게 전송할 JSON" />
        {editorError && <small className="art-prompt-editor-error">{editorError}</small>}
        <footer><button type="button" onClick={() => setIsEditorOpen(false)}>취소</button><button type="button" onClick={saveEditedPrompt}>JSON 저장</button></footer>
      </section>
    </div>}
  </section>;
}
