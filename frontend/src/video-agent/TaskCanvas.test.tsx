import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TaskCanvas } from "./TaskCanvas";
import { buildUnresolvedScenes } from "../resume-utils";
import type { Task } from "./types";

describe("TaskCanvas", () => {
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
});
