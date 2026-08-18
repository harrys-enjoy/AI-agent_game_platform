import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows the Korean label for the given state", () => {
    render(<StatusBadge state="TASK_STATE_WORKING" startedAt={Date.now()} />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("생성 중");
  });

  it("ticks the elapsed-time counter every second", () => {
    const startedAt = Date.now();
    render(<StatusBadge state="TASK_STATE_WORKING" startedAt={startedAt} />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("0s");

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId("status-badge")).toHaveTextContent("3s");
  });
});
