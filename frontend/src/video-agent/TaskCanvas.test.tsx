import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskCanvas } from "./TaskCanvas";
import { buildUnresolvedScenes } from "../resume-utils";
import type { Task } from "./types";

describe("TaskCanvas", () => {
  afterEach(() => cleanup());

  it("shows an idle prompt when there is no task", () => {
    render(<TaskCanvas task={null} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId("canvas-idle")).toBeVisible();
  });

  it("shows a working spinner for SUBMITTED and WORKING", () => {
    const task: Task = { id: "t1", contextId: "c1", status: { state: "TASK_STATE_WORKING" } };
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId("canvas-working")).toBeVisible();
  });

  it("renders the completed video from the artifact data part", () => {
    const task: Task = {
      id: "t1",
      contextId: "c1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "영상 초안 결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    };
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId("canvas-completed")).toHaveAttribute("src", "http://x/video.mp4");
  });

  it("caps the completed video's size so it can't overflow into the panel next to it", () => {
    const task: Task = {
      id: "t1",
      contextId: "c1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    };
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);

    const video = screen.getByTestId("canvas-completed");
    expect(video).toHaveClass("max-w-full");
    expect(video.className).not.toMatch(/\bmax-h-full\b/);
  });

  it("offers a way to start a new generation once the video is completed", async () => {
    const task: Task = {
      id: "t1",
      contextId: "c1",
      status: { state: "TASK_STATE_COMPLETED" },
      artifacts: [{ artifactId: "a1", name: "결과", parts: [{ data: { output_video_url: "http://x/video.mp4" } }] }],
    };
    const onRetry = vi.fn();
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={onRetry} />);

    await userEvent.click(screen.getByRole("button", { name: "새로 생성" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders one upload card per unresolved scene and calls onUploadScene independently", async () => {
    const task: Task = { id: "t1", contextId: "c1", status: { state: "TASK_STATE_INPUT_REQUIRED" } };
    const scenes = buildUnresolvedScenes([
      { sceneId: "scene_04", imageUrl: "http://x/s4.png", issues: ["too wide"] },
      { sceneId: "scene_05", imageUrl: "http://x/s5.png", issues: [] },
    ]);
    const onUploadScene = vi.fn();
    render(<TaskCanvas task={task} unresolvedScenes={scenes} onUploadScene={onUploadScene} onRetry={vi.fn()} />);

    const file = new File(["fake"], "fixed.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("scene_04 수정 이미지 업로드"), file);

    expect(onUploadScene).toHaveBeenCalledWith("scene_04", file);
    expect(onUploadScene).toHaveBeenCalledTimes(1);
  });

  it("shows an error view with a retry button for FAILED", async () => {
    const task: Task = { id: "t1", contextId: "c1", status: { state: "TASK_STATE_FAILED" } };
    const onRetry = vi.fn();
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={onRetry} />);

    expect(screen.getByTestId("canvas-error")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("shows the specific failure reason from status.message when present for FAILED", () => {
    const task: Task = {
      id: "t1",
      contextId: "c1",
      status: {
        state: "TASK_STATE_FAILED",
        message: { parts: [{ text: "예산 초과로 렌더링이 중단되었습니다." }] },
      },
    };
    const { container } = render(
      <TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />,
    );
    const scoped = within(container);

    expect(scoped.getByTestId("canvas-error-reason")).toHaveTextContent("예산 초과로 렌더링이 중단되었습니다.");
    expect(scoped.getByText("생성에 실패했습니다.")).toBeVisible();
  });

  it("does not show a detail toggle when the failure has no technical detail part", () => {
    const task: Task = {
      id: "t1",
      contextId: "c1",
      status: { state: "TASK_STATE_FAILED", message: { parts: [{ text: "실패했습니다." }] } },
    };
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);

    expect(screen.queryByText("자세히 보기")).not.toBeInTheDocument();
  });

  it("reveals technical detail behind a toggle when a second message part is present", async () => {
    const task: Task = {
      id: "t1",
      contextId: "c1",
      status: {
        state: "TASK_STATE_FAILED",
        message: {
          parts: [
            { text: "영상 생성에 실패했습니다: Veo call returned no generated videos" },
            { text: "Traceback (most recent call last):\n  ...\nVeoBackendError: Veo call returned no generated videos" },
          ],
        },
      },
    };
    render(<TaskCanvas task={task} unresolvedScenes={[]} onUploadScene={vi.fn()} onRetry={vi.fn()} />);

    expect(screen.queryByTestId("canvas-error-detail")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("자세히 보기"));
    expect(screen.getByTestId("canvas-error-detail")).toHaveTextContent("VeoBackendError");

    await userEvent.click(screen.getByText("자세히 숨기기"));
    expect(screen.queryByTestId("canvas-error-detail")).not.toBeInTheDocument();
  });
});
