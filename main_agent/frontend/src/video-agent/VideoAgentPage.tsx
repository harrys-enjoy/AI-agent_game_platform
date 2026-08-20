import "./styles.css";
import { useEffect, useState } from "react";
import { ChatComposer } from "./ChatComposer";
import { ComposerTabs } from "./ComposerTabs";
import { FormComposer } from "./FormComposer";
import { StatusBadge } from "./StatusBadge";
import { TaskCanvas } from "./TaskCanvas";
import { cancelVideoAgentTask, createVideoAgentTask, resumeVideoAgentScene } from "./api";
import { useVideoTaskPolling } from "./use-video-task-polling";
import { buildUnresolvedScenes, markSceneStatus, mergeResumeResult, type UnresolvedScene } from "../resume-utils";

const STORAGE_KEY = "video-agent-active-task";

function readPersistedTask(): { taskId: string; startedAt: number } | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { taskId: string; startedAt: number };
    return typeof parsed.taskId === "string" && typeof parsed.startedAt === "number" ? parsed : null;
  } catch {
    return null;
  }
}

export function VideoAgentPage({ initialBrief, assignee }: { initialBrief?: string; assignee?: string } = {}) {
  const [taskId, setTaskId] = useState<string | null>(() => readPersistedTask()?.taskId ?? null);
  const [startedAt, setStartedAt] = useState(() => readPersistedTask()?.startedAt ?? Date.now());
  const [clarifyingQuestion, setClarifyingQuestion] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [unresolvedScenes, setUnresolvedScenes] = useState<UnresolvedScene[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const { task, reconnecting, error, notFound, resumePolling } = useVideoTaskPolling(taskId);

  useEffect(() => {
    if (notFound) window.localStorage.removeItem(STORAGE_KEY);
  }, [notFound]);

  useEffect(() => {
    if (task?.status.state === "TASK_STATE_INPUT_REQUIRED" && task.status.unresolvedScenes) {
      setUnresolvedScenes((previous) => (previous.length === 0 ? buildUnresolvedScenes(task.status.unresolvedScenes!) : previous));
    }
  }, [task?.id, task?.status.state, task?.status.unresolvedScenes]);

  async function handleSubmit(message: string) {
    setSubmitError(null);
    setClarifyingQuestion(null);
    setSubmitting(true);
    try {
      const response = await createVideoAgentTask(message, assignee);
      if ("task" in response) {
        setTaskId(response.task.id);
        setStartedAt(Date.now());
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ taskId: response.task.id, startedAt: Date.now() }));
        setUnresolvedScenes([]);
      } else {
        setClarifyingQuestion(response.message.parts.map((part) => part.text).filter(Boolean).join("\n"));
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "요청 제출에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel() {
    if (!taskId) return;
    try {
      await cancelVideoAgentTask(taskId);
      resumePolling();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "취소 요청에 실패했습니다.");
    }
  }

  async function handleUploadScene(sceneId: string, file: File) {
    if (!taskId) return;
    setUnresolvedScenes((scenes) => markSceneStatus(scenes, sceneId, "uploading"));
    try {
      const result = await resumeVideoAgentScene(taskId, sceneId, file);
      setUnresolvedScenes((scenes) => mergeResumeResult(scenes, result));
      resumePolling();
    } catch {
      setUnresolvedScenes((scenes) => markSceneStatus(scenes, sceneId, "error"));
    }
  }

  function handleRetry() {
    setTaskId(null);
    window.localStorage.removeItem(STORAGE_KEY);
    setUnresolvedScenes([]);
    setClarifyingQuestion(null);
  }

  const isBusy = task?.status.state === "TASK_STATE_SUBMITTED" || task?.status.state === "TASK_STATE_WORKING";
  const canCancel = isBusy || task?.status.state === "TASK_STATE_INPUT_REQUIRED";

  return (
    <>
      <div className="title-row">
        <div>
          <p className="eyebrow">MAIN AGENT / VIDEO GENERATION</p>
          <h1>영상 생성</h1>
        </div>
      </div>
      <div className="grid grid-cols-[minmax(280px,360px)_1fr] gap-4">
        <aside className="flex min-h-[520px] flex-col gap-3 rounded-[15px] border border-brief-border bg-white p-4">
          <ComposerTabs
            chat={<ChatComposer disabled={isBusy || submitting} onSubmit={handleSubmit} initialValue={initialBrief} />}
            form={<FormComposer disabled={isBusy || submitting} onSubmit={handleSubmit} />}
          />
          {clarifyingQuestion && (
            <p className="rounded bg-amber-50 p-2 text-sm text-amber-800" data-testid="clarifying-question">
              {clarifyingQuestion}
            </p>
          )}
          {submitError && (
            <p className="rounded bg-red-50 p-2 text-sm text-red-700" data-testid="submit-error">
              {submitError}
            </p>
          )}
          {task && <StatusBadge state={task.status.state} startedAt={startedAt} />}
          {reconnecting && (
            <p className="text-sm text-amber-600" data-testid="reconnecting-banner">
              재연결 중...
            </p>
          )}
          {error && (
            <p className="text-sm text-red-700" data-testid="polling-error">
              {error}
            </p>
          )}
          {canCancel && (
            <button
              type="button"
              onClick={handleCancel}
              className="rounded-[8px] border border-brief-border px-3 py-2 text-sm text-brief-text"
            >
              취소
            </button>
          )}
        </aside>
        <main className="min-h-[520px] rounded-[15px] border border-brief-border bg-white p-4">
          <TaskCanvas task={task} unresolvedScenes={unresolvedScenes} onUploadScene={handleUploadScene} onRetry={handleRetry} />
        </main>
      </div>
    </>
  );
}
