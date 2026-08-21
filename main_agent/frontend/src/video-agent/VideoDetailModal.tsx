import { useEffect, useRef, useState } from "react";
import { getVideoAgentTaskDetail } from "./api";
import type { Task, TaskDetail } from "./types";

const CONFIRM_TIMEOUT_MS = 3000;

function outputVideoUrl(task: Task): string | undefined {
  return task.artifacts
    ?.flatMap((artifact) => artifact.parts)
    .find((part) => typeof part.data?.output_video_url === "string")?.data?.output_video_url as string | undefined;
}

function formatDate(iso: string | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("ko-KR", { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

type Scene = {
  scene_id: string;
  storyboard?: { camera?: string; subject?: string; action?: string; setting?: string };
  prompts?: { image_prompt?: string; video_motion_prompt?: string } | null;
  candidates?: { candidate_id: string; consistency_review?: { passed?: boolean; issues?: string[] } | null }[];
  needs_manual_fix?: boolean;
};

export function VideoDetailModal({
  task,
  onClose,
  onDelete,
}: {
  task: Task | null;
  onClose: () => void;
  onDelete: (taskId: string) => void | Promise<void>;
}) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [showFailureDetail, setShowFailureDetail] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const confirmTimeoutRef = useRef<number | null>(null);
  const taskId = task?.id ?? null;

  useEffect(() => {
    setDetail(null);
    setError(null);
    setShowRaw(false);
    setShowFailureDetail(false);
    setConfirmingDelete(false);
    if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current);
    if (!taskId) return;
    let cancelled = false;
    getVideoAgentTaskDetail(taskId)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "상세 정보를 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  useEffect(() => {
    return () => {
      if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current);
    };
  }, []);

  if (!task) return null;
  const videoUrl = outputVideoUrl(task);
  const createdAtLabel = formatDate(task.createdAt);

  function handleDeleteClick() {
    if (!taskId) return;
    if (confirmingDelete) {
      if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current);
      void onDelete(taskId);
    } else {
      setConfirmingDelete(true);
      confirmTimeoutRef.current = window.setTimeout(() => setConfirmingDelete(false), CONFIRM_TIMEOUT_MS);
    }
  }

  const project = detail?.project as { narrative?: { beats?: unknown[] }; scenes?: Scene[]; running_cost_usd?: number } | null | undefined;
  const scenes = project?.scenes ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      data-testid="video-detail-modal"
    >
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-[15px] bg-white p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-brief-text">영상 상세 정보</h2>
            {createdAtLabel && (
              <p className="mt-0.5 text-xs text-brief-muted" data-testid="video-detail-date">
                생성일: {createdAtLabel}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDeleteClick}
              className={`rounded-[8px] px-2 py-1 text-xs font-semibold ${
                confirmingDelete ? "bg-red-600 text-white" : "border border-brief-border text-red-600"
              }`}
              data-testid="video-detail-delete"
            >
              {confirmingDelete ? "정말 삭제할까요?" : "삭제"}
            </button>
            <button type="button" onClick={onClose} className="text-brief-muted" aria-label="닫기">
              ✕
            </button>
          </div>
        </div>

        {videoUrl && (
          <video src={videoUrl} controls autoPlay className="mb-3 max-h-[50vh] w-full rounded-[10px] bg-black" />
        )}

        {task.status.state === "TASK_STATE_FAILED" && (
          <div className="mb-3 rounded-[10px] border border-red-200 bg-red-50 p-3" data-testid="video-detail-failure">
            <p className="text-xs font-semibold uppercase text-red-700">생성 실패 사유</p>
            <p className="mt-1 whitespace-pre-wrap text-sm text-red-800">
              {task.status.message?.parts[0]?.text || "실패 사유가 기록되지 않았습니다."}
            </p>
            {task.status.message?.parts[1]?.text && (
              <>
                <button
                  type="button"
                  onClick={() => setShowFailureDetail((value) => !value)}
                  className="mt-2 text-xs text-red-700 underline"
                >
                  {showFailureDetail ? "기술 세부사항 숨기기" : "기술 세부사항 보기"}
                </button>
                {showFailureDetail && (
                  <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-red-200 bg-white p-2 text-xs text-red-900">
                    {task.status.message.parts[1].text}
                  </pre>
                )}
              </>
            )}
          </div>
        )}

        {error && (
          <p className="rounded bg-red-50 p-2 text-sm text-red-700" data-testid="video-detail-error">
            {error}
          </p>
        )}
        {!error && !detail && (
          <div className="flex h-24 items-center justify-center text-brief-muted" data-testid="video-detail-loading">
            불러오는 중...
          </div>
        )}
        {!error && detail && (
          <div className="flex flex-col gap-4 text-sm text-brief-text">
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase text-brief-muted">프롬프트</h3>
              <p className="whitespace-pre-wrap rounded bg-brief-bg p-2">{detail.brief || "(기록된 프롬프트 없음)"}</p>
            </div>

            {scenes.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase text-brief-muted">장면별 생성 기록 ({scenes.length}개)</h3>
                <div className="flex flex-col gap-2">
                  {scenes.map((scene) => (
                    <div key={scene.scene_id} className="rounded border border-brief-border p-2" data-testid={`scene-detail-${scene.scene_id}`}>
                      <p className="mb-1 text-xs font-semibold text-brief-text">{scene.scene_id}</p>
                      {scene.storyboard && (
                        <p className="text-xs text-brief-muted">
                          {[scene.storyboard.camera, scene.storyboard.subject, scene.storyboard.action, scene.storyboard.setting]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      )}
                      {scene.prompts?.image_prompt && (
                        <p className="mt-1 whitespace-pre-wrap text-xs text-brief-muted">이미지 프롬프트: {scene.prompts.image_prompt}</p>
                      )}
                      {scene.candidates?.map((candidate) => (
                        <p key={candidate.candidate_id} className="mt-1 text-xs">
                          {candidate.consistency_review?.passed === false ? (
                            <span className="text-red-600">검수 실패: {candidate.consistency_review.issues?.join(", ")}</span>
                          ) : candidate.consistency_review?.passed ? (
                            <span className="text-brief-accent-dark">검수 통과</span>
                          ) : null}
                        </p>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {project == null && !error ? (
              <p className="text-xs text-brief-muted">저장된 생성 기록이 없습니다. 장면 생성이 시작되기 전에 중단됐습니다.</p>
            ) : (
              <div>
                <button type="button" onClick={() => setShowRaw((value) => !value)} className="text-xs text-brief-muted underline">
                  {showRaw ? "원본 데이터 숨기기" : "원본 데이터 보기"}
                </button>
                {showRaw && (
                  <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-brief-border bg-brief-bg p-2 text-xs">
                    {JSON.stringify(detail.project, null, 2)}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
