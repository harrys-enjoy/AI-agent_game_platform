import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MainBriefingChatbot } from "./MainUiPanels";

describe("MainBriefingChatbot", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the default empty-state text, placeholder, and header when no contextHint is given", () => {
    render(<MainBriefingChatbot />);
    expect(screen.getByText("간단한 질문이나 업무 내용을 입력하세요.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("무엇을 도와드릴까요?")).toBeInTheDocument();
    expect(screen.getByText("Main Chatbot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset chat" })).toBeInTheDocument();
  });

  it("shows the contextHint as the empty-state text and an English placeholder when provided", () => {
    render(
      <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />,
    );
    expect(
      screen.getByText("다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요."),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Type a message...")).toBeInTheDocument();
  });

  it("shows the AI Chat · Video Generation header and Reset chat button when contextHint is given", () => {
    render(<MainBriefingChatbot contextHint="영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />);
    expect(screen.getByText("AI Chat · Video Generation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset chat" })).toBeInTheDocument();
  });

  it("Reset chat calls the backend reset endpoint and clears the conversation", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ messages: [] }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<MainBriefingChatbot contextHint="영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />);

    await userEvent.type(screen.getByPlaceholderText("Type a message..."), "영상 관련 질문");
    await userEvent.click(screen.getByRole("button", { name: "➤" }));
    expect(screen.getByText("영상 관련 질문")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reset chat" }));

    await waitFor(() => expect(screen.queryByText("영상 관련 질문")).not.toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/chats/Main%20Chatbot/reset"), expect.objectContaining({ method: "POST" }));
  });

  it("uses the Main routing API and dispatches an automatic handoff without generating a Main answer", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/api/main-route")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            targetAgent: "workmate-agent",
            targetChat: "Workmate AI",
            originalRequest: "오늘 브리핑 해줘",
            handoff: "automatic",
          }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({ messages: [] }) });
    });
    vi.stubGlobal("fetch", fetchMock);
    const routeListener = vi.fn();
    window.addEventListener("main-chat-route", routeListener);
    render(<MainBriefingChatbot />);

    const input = screen.getByPlaceholderText("무엇을 도와드릴까요?");
    await userEvent.type(input, "오늘 브리핑 해줘");
    await userEvent.click(screen.getByRole("button", { name: "➤" }));

    await waitFor(() => expect(routeListener).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/main-route",
      expect.objectContaining({ body: JSON.stringify({ content: "오늘 브리핑 해줘" }) }),
    );
    expect((routeListener.mock.calls[0][0] as CustomEvent).detail).toEqual({
      chat: "Workmate AI",
      message: "오늘 브리핑 해줘",
      handoff: "automatic",
    });
    expect(screen.getByText("Workmate AI로 연결합니다.")).toBeInTheDocument();
    window.removeEventListener("main-chat-route", routeListener);
  });
});
