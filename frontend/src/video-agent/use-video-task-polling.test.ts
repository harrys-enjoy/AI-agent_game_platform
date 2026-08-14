import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVideoTaskPolling } from "./use-video-task-polling";
import * as api from "./api";
import type { Task } from "./types";

function task(state: Task["status"]["state"]): Task {
  return { id: "task_1", contextId: "ctx_1", status: { state } };
}

describe("useVideoTaskPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("does nothing when taskId is null", () => {
    const spy = vi.spyOn(api, "getVideoAgentTask");
    renderHook(() => useVideoTaskPolling(null));
    expect(spy).not.toHaveBeenCalled();
  });

  it("polls again 5s after a non-terminal response", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockResolvedValue(task("TASK_STATE_WORKING"));
    renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("stops polling once a terminal state is reached", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockResolvedValue(task("TASK_STATE_COMPLETED"));
    renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("pauses on INPUT_REQUIRED and resumes only after resumePolling() is called", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockResolvedValue(task("TASK_STATE_INPUT_REQUIRED"));
    const { result } = renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(spy).toHaveBeenCalledTimes(1);

    spy.mockResolvedValue(task("TASK_STATE_WORKING"));
    act(() => result.current.resumePolling());
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it("shows a reconnecting banner on the first failures but not an error", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(result.current.reconnecting).toBe(true));
    expect(result.current.error).toBeNull();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("escalates to an error after 3 consecutive failures", async () => {
    const spy = vi.spyOn(api, "getVideoAgentTask").mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useVideoTaskPolling("task_1"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    await waitFor(() => expect(result.current.error).toBe("network down"));
  });
});
