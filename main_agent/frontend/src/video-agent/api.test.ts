import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelVideoAgentTask, createVideoAgentTask, getVideoAgentTask, resumeVideoAgentScene } from "./api";

describe("video-agent api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the message and returns the task", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_SUBMITTED" } } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createVideoAgentTask("15초 이벤트 영상 만들어줘", "테스트 담당자");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/video-agent/tasks",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ message: "15초 이벤트 영상 만들어줘", owner: "테스트 담당자" }) }),
    );
    expect("task" in result && result.task.id).toBe("task_1");
  });

  it("throws when task creation fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
    await expect(createVideoAgentTask("브리프")).rejects.toThrow("HTTP 502");
  });

  it("fetches a task by id from the encoded url", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task: { id: "task 1", contextId: "ctx_1", status: { state: "TASK_STATE_WORKING" } } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const task = await getVideoAgentTask("task 1");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/video-agent/tasks/task%201");
    expect(task.status.state).toBe("TASK_STATE_WORKING");
  });

  it("cancels a task", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task: { id: "task_1", contextId: "ctx_1", status: { state: "TASK_STATE_CANCELED" } } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const task = await cancelVideoAgentTask("task_1");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/video-agent/tasks/task_1/cancel", { method: "POST" });
    expect(task.status.state).toBe("TASK_STATE_CANCELED");
  });

  it("uploads a scene resume file as form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ scene_id: "scene_04", resolved: true, remaining_unresolved: [], output_video_url: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["fake"], "fixed.png", { type: "image/png" });
    const result = await resumeVideoAgentScene("task_1", "scene_04", file);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/video-agent/tasks/task_1/scenes/scene_04/resume",
      expect.objectContaining({ method: "POST" }),
    );
    const call = fetchMock.mock.calls[0][1] as { body: FormData };
    expect((call.body.get("file") as File).name).toBe("fixed.png");
    expect(result.resolved).toBe(true);
  });
});
