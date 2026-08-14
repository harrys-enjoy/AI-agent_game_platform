// frontend/src/video-agent/VideoAgentPage.tsx
import { useEffect, useState } from "react";
import { ChatComposer } from "./ChatComposer";
import { ComposerTabs } from "./ComposerTabs";
import { FormComposer } from "./FormComposer";
import { StatusBadge } from "./StatusBadge";
import { TaskCanvas } from "./TaskCanvas";
import { cancelVideoAgentTask, createVideoAgentTask, resumeVideoAgentScene } from "./api";
import { useVideoTaskPolling } from "./use-video-task-polling";
import { buildUnresolvedScenes, markSceneStatus, mergeResumeResult, type UnresolvedScene } from "../resume-utils";

export function VideoAgentPage() {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(() => Date.now());
  const [clarifyingQuestion, setClarifyingQuestion] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [unresolvedScenes, setUnresolvedScenes] = useState<UnresolvedScene[]>([]);
  const { task, reconnecting, error, resumePolling } = useVideoTaskPolling(taskId);

  useEffect(() => {
    if (task?.status.state === "TASK_STATE_INPUT_REQUIRED" && task.status.unresolvedScenes) {
      setUnresolvedScenes((previous) => (previous.length === 0 ? buildUnresolvedScenes(task.status.unresolvedScenes!) : previous));
    }
  }, [task?.id, task?.status.state, task?.status.unresolvedScenes]);

  async function handleSubmit(message: string) {
    setSubmitError(null);
    setClarifyingQuestion(null);
    try {
      const response = await createVideoAgentTask(message);
      if ("task" in response) {
        setTaskId(response.task.id);
        setStartedAt(Date.now());
        setUnresolvedScenes([]);
      } else {
        setClarifyingQuestion(response.message.parts.map((part) => part.text).filter(Boolean).join("\n"));
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "요청 제출에 실패했습니다.");
    }
  }

  async function handleCancel() {
    if (!taskId) return;
    await cancelVideoAgentTask(taskId);
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
    setUnresolvedScenes([]);
    setClarifyingQuestion(null);
  }

  const isBusy = task?.status.state === "TASK_STATE_SUBMITTED" || task?.status.state === "TASK_STATE_WORKING";

  return (
    <div className="grid h-screen grid-cols-[minmax(280px,360px)_1fr] gap-4 bg-slate-50 p-4">
      <aside className="flex flex-col gap-3 rounded-lg bg-white p-4 shadow-sm">
        <h1 className="text-lg font-semibold">영상 생성</h1>
        <ComposerTabs
          chat={<ChatComposer disabled={isBusy} onSubmit={handleSubmit} />}
          form={<FormComposer disabled={isBusy} onSubmit={handleSubmit} />}
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
        {isBusy && (
          <button type="button" onClick={handleCancel} className="rounded border border-slate-300 px-3 py-2 text-sm">
            취소
          </button>
        )}
      </aside>
      <main className="rounded-lg bg-white p-4 shadow-sm">
        <TaskCanvas task={task} unresolvedScenes={unresolvedScenes} onUploadScene={handleUploadScene} onRetry={handleRetry} />
      </main>
    </div>
  );
}
