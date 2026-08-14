import { useEffect, useRef, useState } from "react";
import { getVideoAgentTask } from "./api";
import type { Task, TaskState } from "./types";

const POLL_INTERVAL_MS = 5000;
const MAX_CONSECUTIVE_FAILURES = 3;
const TERMINAL_STATES: TaskState[] = ["TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"];

export type PollingState = {
  task: Task | null;
  reconnecting: boolean;
  error: string | null;
  resumePolling: () => void;
};

export function useVideoTaskPolling(taskId: string | null): PollingState {
  const [task, setTask] = useState<Task | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumeSignal, setResumeSignal] = useState(0);
  const failureCountRef = useRef(0);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      setReconnecting(false);
      setError(null);
      return;
    }
    failureCountRef.current = 0;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const result = await getVideoAgentTask(taskId as string);
        if (cancelled) return;
        failureCountRef.current = 0;
        setReconnecting(false);
        setError(null);
        setTask(result);
        const paused = TERMINAL_STATES.includes(result.status.state) || result.status.state === "TASK_STATE_INPUT_REQUIRED";
        if (!paused) timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled) return;
        failureCountRef.current += 1;
        if (failureCountRef.current >= MAX_CONSECUTIVE_FAILURES) {
          setReconnecting(false);
          setError(err instanceof Error ? err.message : "video-agent polling failed");
        } else {
          setReconnecting(true);
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId, resumeSignal]);

  function resumePolling() {
    failureCountRef.current = 0;
    setResumeSignal((n) => n + 1);
  }

  return { task, reconnecting, error, resumePolling };
}
