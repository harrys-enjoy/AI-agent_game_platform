import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App - Video Generation sidebar entry", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("renders VideoAgentPage instead of the generic chat panel when Video Generation is selected", async () => {
    render(<App />);

    await userEvent.click(screen.getByText("Video Generation"));

    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Type a message...")).toBeInTheDocument();
    expect(screen.queryByText("Type a message to start a conversation")).not.toBeInTheDocument();
  });

  it("restores the generic chat panel when switching away from Video Generation", async () => {
    render(<App />);

    await userEvent.click(screen.getByText("Video Generation"));
    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Workmate AI"));

    expect(await screen.findByPlaceholderText("Type a message...")).toBeInTheDocument();
    expect(screen.queryByLabelText("영상 브리프")).not.toBeInTheDocument();
  });

  it("shows the scoped routing chatbot instead of the default one when Video Generation is selected", async () => {
    render(<App />);

    await userEvent.click(screen.getByText("Video Generation"));

    expect(await screen.findByPlaceholderText("Type a message...")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("무엇을 도와드릴까요?")).not.toBeInTheDocument();
  });

  it("keeps Video Generation open when its own chat mentions another agent domain", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Video Generation"));
    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();

    const chatbotInput = screen.getByPlaceholderText("Type a message...");
    await userEvent.type(chatbotInput, "코드 버그 확인해줘");
    const chatbotSubmit = chatbotInput.closest("form")?.querySelector("button[type='submit']") as HTMLButtonElement;
    await userEvent.click(chatbotSubmit);

    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();
  });

  it("keeps the video-agent page in place when the routing chatbot gets a non-matching message", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Video Generation"));
    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();

    const chatbotInput = screen.getByPlaceholderText("Type a message...");
    await userEvent.type(chatbotInput, "안녕하세요");
    const chatbotSubmit = chatbotInput.closest("form")?.querySelector("button[type='submit']") as HTMLButtonElement;
    await userEvent.click(chatbotSubmit);

    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();
  });

  it("keeps Video Generation open when its own chat receives a story request", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Video Generation"));
    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();

    const chatbotInput = screen.getByPlaceholderText("Type a message...");
    await userEvent.type(chatbotInput, "스토리 검토해줘");
    const chatbotSubmit = chatbotInput.closest("form")?.querySelector("button[type='submit']") as HTMLButtonElement;
    await userEvent.click(chatbotSubmit);

    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();
  });

  it("automatically sends an automatic Main handoff to the selected Agent Chat", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/api/chats/Workmate%20AI/reply")) {
        return Promise.resolve({ ok: true, json: async () => ({ answer: "Workmate 브리핑 결과" }) });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    window.dispatchEvent(new CustomEvent("main-chat-route", {
      detail: { chat: "Workmate AI", message: "오늘 브리핑 해줘", handoff: "automatic" },
    }));

    expect(await screen.findByText("Workmate 브리핑 결과")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/chats/Workmate%20AI/reply",
      expect.objectContaining({ body: expect.stringContaining("오늘 브리핑 해줘") }),
    );
  });

  it("switches from Game Q&A to Workmate when the reply names Workmate as the target chat", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/api/chats/Game%20Q%26A/reply")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ answer: "회의 시간을 알려주세요.", agent: "workmate-agent", target_chat: "Workmate AI", status: "succeeded" }),
        });
      }
      if (url.includes("/session")) return Promise.resolve({ ok: true, json: async () => ({ session_id: "session-1", messages: [] }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await userEvent.click(screen.getByText("Game Q&A"));
    const input = await screen.findByPlaceholderText("Type /? for Game Q&A commands...");
    await userEvent.type(input, "다음 주 회의 일정 잡아줘");
    await userEvent.click(input.closest("form")!.querySelector("button[type='submit']")!);

    expect(await screen.findByRole("heading", { name: /AI Chat · Workmate AI/ })).toBeInTheDocument();
  });

  it("prefills Video Generation without sending a confirmation-required Main handoff", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    window.dispatchEvent(new CustomEvent("main-chat-route", {
      detail: { chat: "Video Generation", message: "할로윈 이벤트 영상", handoff: "confirmation_required" },
    }));

    expect(await screen.findByLabelText("영상 브리프")).toHaveValue("할로윈 이벤트 영상");
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/chats/Video%20Generation/reply"),
      expect.anything(),
    ));
  });
});
