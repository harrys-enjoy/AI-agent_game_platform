// `/api/v1/internal/skill-chat/messages` 호출 하나를 React 상태(loading/error/
// data/warnings)로 감싸는 공통 Hook. `workmate-ui/lib/use-skill.ts`에서
// 이식(19번 문서 2단계) — 원본은 `{apiBase, token}`(OIDC)을 썼지만, 여기서는
// 결정 5에 따라 `{apiBase, assignee}`로 인증한다(오케스트레이터가 이미 아는
// "담당자" 선택을 그대로 씀 — 별도 토큰 입력 UI가 필요 없다).

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, skillChatApi, WORKMATE_API_BASE_URL } from "./api";
import type { SkillChatResponse, SkillWarning } from "./types";

type SkillState<T> = {
  loading: boolean;
  error: string | null;
  data: T | null;
  warnings: SkillWarning[];
};

function initialState<T>(): SkillState<T> {
  return { loading: false, error: null, data: null, warnings: [] };
}

export function useSkillRunner<T>(skillId: string, assignee: string) {
  const [state, setState] = useState<SkillState<T>>(initialState);

  const run = useCallback(
    async (input: Record<string, unknown>): Promise<SkillChatResponse | null> => {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      try {
        const response = await skillChatApi.send({ apiBase: WORKMATE_API_BASE_URL, assignee }, skillId, input);
        const data = (response.artifact.data && "data" in response.artifact.data ? response.artifact.data.data : null) as T | null;
        setState({ loading: false, error: null, data, warnings: response.warnings });
        return response;
      } catch (error) {
        const message = error instanceof ApiError ? error.message : `예상치 못한 오류: ${(error as Error).message}`;
        setState({ loading: false, error: message, data: null, warnings: [] });
        return null;
      }
    },
    [assignee, skillId],
  );

  return { ...state, run };
}

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

// SDK/어댑터마다 Task 상태의 표기가 다를 수 있으므로 내부에서 하나의 상태로 정규화한다.
const COMPLETED_STATES = new Set(["TASK_STATE_COMPLETED", "completed", "succeeded", "success"]);
const TERMINAL_FAILURE_STATES = new Set([
  "TASK_STATE_FAILED",
  "TASK_STATE_CANCELED",
  "TASK_STATE_CANCELLED",
  "TASK_STATE_REJECTED",
  "failed",
  "canceled",
  "cancelled",
  "rejected",
]);

export function normalizeTaskState(state: unknown): string {
  return typeof state === "string" ? state.trim().toLowerCase() : "";
}

/**
 * `analyze_meeting`처럼 `state: "submitted"`로 즉시 응답하고 실제 결과는
 * `GET .../tasks/{task_id}` Polling으로 받는 Skill 전용 Hook이다(5단계
 * 회의 관리에서 사용).
 */
export function usePollingSkillRunner<T>(skillId: string, assignee: string, fetchResult: () => Promise<T>) {
  const [state, setState] = useState<SkillState<T>>(initialState);
  const cancelledRef = useRef(false);
  useEffect(
    () => () => {
      cancelledRef.current = true;
    },
    [],
  );

  const run = useCallback(
    async (input: Record<string, unknown>): Promise<T | null> => {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      try {
        const config = { apiBase: WORKMATE_API_BASE_URL, assignee };
        const submitted = await skillChatApi.send(config, skillId, input);
        const startedAt = Date.now();
        while (!cancelledRef.current) {
          // 분석 결과 저장과 Task 상태 갱신 사이에 지연이 생길 수 있다.
          // 결과 조회가 성공하면 Task 상태가 오래된 경우에도 즉시 완료 처리한다.
          try {
            const persistedData = await fetchResult();
            if (!cancelledRef.current) setState({ loading: false, error: null, data: persistedData, warnings: [] });
            return persistedData;
          } catch {
            // 아직 저장되지 않은 동안에는 Task Snapshot을 계속 확인한다.
          }
          const task = await skillChatApi.getTask(config, submitted.task_id);
          const taskState = task.status.state;
          const normalizedState = normalizeTaskState(taskState);
          if (COMPLETED_STATES.has(taskState) || COMPLETED_STATES.has(normalizedState) || normalizedState === "task_state_completed") {
            const warnings = task.artifacts?.[0]?.metadata?.warnings ?? [];
            const data = await fetchResult();
            if (!cancelledRef.current) setState({ loading: false, error: null, data, warnings });
            return data;
          }
          if (TERMINAL_FAILURE_STATES.has(taskState) || TERMINAL_FAILURE_STATES.has(normalizedState) || normalizedState.startsWith("task_state_failed")) {
            const message = task.status.message?.parts?.[0]?.text ?? `${skillId} 실행이 실패했습니다.`;
            if (!cancelledRef.current) setState({ loading: false, error: message, data: null, warnings: [] });
            return null;
          }
          if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
            if (!cancelledRef.current) setState({ loading: false, error: "분석이 시간 내에 끝나지 않았습니다. 잠시 후 다시 시도하세요.", data: null, warnings: [] });
            return null;
          }
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        }
        return null;
      } catch (error) {
        const message = error instanceof ApiError ? error.message : `예상치 못한 오류: ${(error as Error).message}`;
        if (!cancelledRef.current) setState({ loading: false, error: message, data: null, warnings: [] });
        return null;
      }
    },
    [assignee, skillId, fetchResult],
  );

  return { ...state, run };
}
