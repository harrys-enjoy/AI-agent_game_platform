import { useEffect, useState } from "react";
import type { TaskState } from "./types";

const LABELS: Record<TaskState, string> = {
  TASK_STATE_SUBMITTED: "제출됨",
  TASK_STATE_WORKING: "생성 중",
  TASK_STATE_INPUT_REQUIRED: "수동 수정 필요",
  TASK_STATE_AUTH_REQUIRED: "인증 필요",
  TASK_STATE_COMPLETED: "완료",
  TASK_STATE_FAILED: "실패",
  TASK_STATE_CANCELED: "취소됨",
  TASK_STATE_REJECTED: "거부됨",
};

export function StatusBadge({ state, startedAt }: { state: TaskState; startedAt: number }) {
  const [elapsedSec, setElapsedSec] = useState(() => Math.floor((Date.now() - startedAt) / 1000));

  useEffect(() => {
    const interval = setInterval(() => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  return (
    <div className="flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-sm" data-testid="status-badge">
      <span>{LABELS[state]}</span>
      <span className="text-slate-400">{elapsedSec}s</span>
    </div>
  );
}
