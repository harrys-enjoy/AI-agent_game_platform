// frontend/src/video-agent/VideoAgentPage.test.tsx
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VideoAgentPage } from "./VideoAgentPage";
import * as api from "./api";

describe("VideoAgentPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("submits a chat brief, creates a task, and shows it working then completed", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({
      task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } },
    });
    vi.spyOn(api, "getVideoAgentTask").mockResolvedValue({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "영상 초안 결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("canvas-completed")).toHaveAttribute("src", "http://x/video.mp4"));
  });

  it("shows the clarifying question inline instead of creating a task", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({ message: { parts: [{ text: "어떤 영상을 원하시나요?" }] } });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "안녕하세요 도와주세요");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("clarifying-question")).toHaveTextContent("어떤 영상을 원하시나요?"));
    expect(screen.getByTestId("canvas-idle")).toBeVisible();
  });

  it("shows an inline error and keeps the composer filled in when submission fails", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockRejectedValue(new Error("video-agent task create failed: HTTP 502"));

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("submit-error")).toBeVisible());
    expect(screen.getByLabelText("영상 브리프")).toHaveValue("할로윈 이벤트 영상 15초");
  });

  it("uploading a resolved scene resumes polling and shows the finished video", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({
      task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } },
    });
    const getTask = vi.spyOn(api, "getVideoAgentTask");
    getTask.mockResolvedValueOnce({
      id: "task_1",
      contextId: "ctx_1",
      status: {
        state: "TASK_STATE_INPUT_REQUIRED",
        unresolvedScenes: [{ sceneId: "scene_04", imageUrl: "http://x/s4.png", issues: ["too wide"] }],
      },
    });
    vi.spyOn(api, "resumeVideoAgentScene").mockResolvedValue({
      scene_id: "scene_04",
      resolved: true,
      remaining_unresolved: [],
      output_video_url: "http://x/video.mp4",
    });
    getTask.mockResolvedValueOnce({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "영상 초안 결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("scene-card-scene_04")).toBeVisible());
    const file = new File(["fake"], "fixed.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("scene_04 수정 이미지 업로드"), file);

    await waitFor(() => expect(screen.getByTestId("canvas-completed")).toHaveAttribute("src", "http://x/video.mp4"));
  });

  it("shows an inline error when canceling a task fails", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({
      task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } },
    });
    vi.spyOn(api, "getVideoAgentTask").mockResolvedValue({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_WORKING" },
    });
    vi.spyOn(api, "cancelVideoAgentTask").mockRejectedValue(new Error("video-agent task cancel failed: HTTP 400"));

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "취소" })).toBeVisible());
    await userEvent.click(screen.getByRole("button", { name: "취소" }));

    await waitFor(() => expect(screen.getByTestId("submit-error")).toHaveTextContent("video-agent task cancel failed: HTTP 400"));
  });

  it("clears a stale persisted task from localStorage once the server reports it as not found", async () => {
    window.localStorage.setItem("video-agent-active-task", JSON.stringify({ taskId: "task_stale", startedAt: Date.now() }));
    vi.spyOn(api, "getVideoAgentTask").mockRejectedValue(new api.VideoAgentTaskNotFoundError("video-agent task not found: task_stale"));

    render(<VideoAgentPage />);

    await waitFor(() => expect(screen.getByTestId("polling-error")).toHaveTextContent("video-agent task not found: task_stale"));
    expect(window.localStorage.getItem("video-agent-active-task")).toBeNull();
  });

  it("shows a cancel button while a task needs a manual fix, and reflects the canceled state after canceling", async () => {
    vi.spyOn(api, "createVideoAgentTask").mockResolvedValue({
      task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } },
    });
    const getTask = vi.spyOn(api, "getVideoAgentTask");
    getTask.mockResolvedValueOnce({
      id: "task_1",
      contextId: "ctx_1",
      status: {
        state: "TASK_STATE_INPUT_REQUIRED",
        unresolvedScenes: [{ sceneId: "scene_04", imageUrl: "http://x/s4.png", issues: ["too wide"] }],
      },
    });
    vi.spyOn(api, "cancelVideoAgentTask").mockResolvedValue({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_CANCELED" },
    });
    getTask.mockResolvedValueOnce({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_CANCELED" },
    });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    await waitFor(() => expect(screen.getByTestId("scene-card-scene_04")).toBeVisible());
    await userEvent.click(screen.getByRole("button", { name: "취소" }));

    await waitFor(() => expect(screen.getByTestId("canvas-error")).toHaveTextContent("취소되었습니다."));
  });

  it("disables the composer immediately on submit, before the first poll response lands", async () => {
    let resolveCreate: (value: Awaited<ReturnType<typeof api.createVideoAgentTask>>) => void = () => {};
    vi.spyOn(api, "createVideoAgentTask").mockReturnValue(
      new Promise((resolve) => {
        resolveCreate = resolve;
      }),
    );
    vi.spyOn(api, "getVideoAgentTask").mockResolvedValue({
      id: "task_1",
      contextId: "ctx_1",
      status: { state: "TASK_STATE_WORKING" },
    });

    render(<VideoAgentPage />);
    await userEvent.type(screen.getByLabelText("영상 브리프"), "할로윈 이벤트 영상 15초");
    const submitButton = screen.getByRole("button", { name: "생성 요청" });
    await userEvent.click(submitButton);

    expect(submitButton).toBeDisabled();

    resolveCreate({ task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } } });
    await waitFor(() => expect(screen.getByTestId("canvas-working")).toBeVisible());
  });

  it("shows the Main Agent page title above the two-panel layout", () => {
    render(<VideoAgentPage />);
    expect(screen.getByText("MAIN AGENT / VIDEO GENERATION")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "영상 생성" })).toBeInTheDocument();
  });

  it("does not stretch the two-panel layout to the full viewport height", () => {
    const { container } = render(<VideoAgentPage />);
    const grid = container.querySelector(".grid");
    expect(grid).not.toHaveClass("h-full");
    expect(container.querySelector("aside")).toHaveClass("min-h-[520px]");
    expect(container.querySelector("main")).toHaveClass("min-h-[520px]");
  });
});
