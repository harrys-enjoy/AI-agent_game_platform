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

const TERMINAL_STATES: TaskState[] = ["TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"];

const DOT_COLORS: Record<TaskState, string> = {
  TASK_STATE_SUBMITTED: "text-brief-accent",
  TASK_STATE_WORKING: "text-brief-accent",
  TASK_STATE_INPUT_REQUIRED: "text-amber-600",
  TASK_STATE_AUTH_REQUIRED: "text-amber-600",
  TASK_STATE_COMPLETED: "text-brief-accent-dark",
  TASK_STATE_FAILED: "text-red-600",
  TASK_STATE_CANCELED: "text-brief-muted",
  TASK_STATE_REJECTED: "text-red-600",
};

export function StatusBadge({ state, startedAt }: { state: TaskState; startedAt: number }) {
  const [elapsedSec, setElapsedSec] = useState(() => Math.floor((Date.now() - startedAt) / 1000));

  useEffect(() => {
    if (TERMINAL_STATES.includes(state)) return;
    const interval = setInterval(() => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [startedAt, state]);

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-brief-border bg-white px-3 py-1 text-sm text-brief-text"
      data-testid="status-badge"
    >
      <span aria-hidden className={DOT_COLORS[state]}>●</span>
      <span>{LABELS[state]}</span>
      <span className="text-brief-muted">{elapsedSec}s</span>
    </div>
  );
}
