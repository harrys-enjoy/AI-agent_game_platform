import { cleanup, render, screen } from "@testing-library/react";
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
    expect(screen.queryByRole("button", { name: "Reset chat" })).not.toBeInTheDocument();
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

  it("Reset chat clears the local conversation without any network calls", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<MainBriefingChatbot contextHint="영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />);

    await userEvent.type(screen.getByPlaceholderText("Type a message..."), "영상 관련 질문");
    await userEvent.click(screen.getByRole("button", { name: "➤" }));
    expect(screen.getByText("영상 관련 질문")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reset chat" }));

    expect(screen.queryByText("영상 관련 질문")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
