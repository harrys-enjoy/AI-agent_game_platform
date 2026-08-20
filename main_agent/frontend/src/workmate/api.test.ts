import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, checkHealth, meetingsApi, proposalsApi, skillChatApi, tasksApi } from "./api";

const config = { apiBase: "http://127.0.0.1:8100", assignee: "서선정" };

describe("workmate api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("checks health without any auth header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);

    const result = await checkHealth("http://127.0.0.1:8100");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8100/health/ready");
    expect(result).toEqual({ ok: true, status: 200 });
  });

  it("percent-encodes the assignee name into X-Workmate-Assignee", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => "[]" });
    vi.stubGlobal("fetch", fetchMock);

    await tasksApi.list(config);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8100/api/v1/tasks",
      expect.objectContaining({ headers: expect.objectContaining({ "X-Workmate-Assignee": "%EC%84%9C%EC%84%A0%EC%A0%95" }) }),
    );
  });

  it("throws before fetching when assignee is blank", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(tasksApi.list({ apiBase: "http://127.0.0.1:8100", assignee: "" })).rejects.toThrow("담당자를 선택하세요.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("creates a task with the manual source type", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ task_id: "t1", title: "테스트", status: "todo" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const task = await tasksApi.create(config, { title: "테스트" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8100/api/v1/tasks",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ title: "테스트", source_type: "manual" }) }),
    );
    expect(task.task_id).toBe("t1");
  });

  it("wraps a non-2xx JSON error body into ApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 400, text: async () => JSON.stringify({ detail: "unknown assignee" }) });
    vi.stubGlobal("fetch", fetchMock);

    await expect(tasksApi.list(config)).rejects.toMatchObject({ status: 400, message: "HTTP 400: unknown assignee" });
  });

  it("uses the assignee header (not OIDC bearer) for Gmail/Calendar-backed proposal review", async () => {
    // 2026-08-19 — 로컬 전용 프로젝트 서버라 제안함도 나머지 6개 화면과 같은 담당자
    // 헤더 인증으로 완화했다(workmate-agent `_authenticated_user_or_assignee` 전환과
    // 짝, `api.ts` 상단 주석 참고). 진짜 Gmail/Calendar 접근(OAuth Consent)은
    // `googleAuthApi.start()`가 여는 팝업으로 별도 처리되므로 이 완화 대상이 아니다.
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify({ decision: "approve", source_type: "email", source_id: "m1" }) });
    vi.stubGlobal("fetch", fetchMock);

    await proposalsApi.reviewEmail(config, { message_id: "m1", decision: "approve" }, "key-1");

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((options.headers as Record<string, string>)["X-Workmate-Assignee"]).toBe("%EC%84%9C%EC%84%A0%EC%A0%95");
    expect((options.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("throws before fetching when a proposal review call has no assignee", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(proposalsApi.reviewEmail({ apiBase: "http://127.0.0.1:8100", assignee: "" }, { message_id: "m1", decision: "approve" }, "key-1")).rejects.toThrow("담당자를 선택하세요.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("polls a skill-chat task snapshot with the assignee header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify({ id: "task-1", status: { state: "TASK_STATE_COMPLETED" } }) });
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = await skillChatApi.getTask(config, "task-1");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8100/api/v1/internal/skill-chat/tasks/task-1", expect.anything());
    expect(snapshot.status.state).toBe("TASK_STATE_COMPLETED");
  });

  it("lists meetings with the assignee header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => "[]" });
    vi.stubGlobal("fetch", fetchMock);

    await meetingsApi.list(config);

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8100/api/v1/meetings", expect.anything());
  });

  it("re-exports ApiError with status and detail", () => {
    const error = new ApiError("HTTP 404: not found", 404, "not found");
    expect(error.status).toBe(404);
    expect(error.detail).toBe("not found");
  });
});
