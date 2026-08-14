import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MainBriefingChatbot } from "./MainUiPanels";

describe("MainBriefingChatbot", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the default empty-state text and placeholder when no contextHint is given", () => {
    render(<MainBriefingChatbot />);
    expect(screen.getByText("간단한 질문이나 업무 내용을 입력하세요.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("무엇을 도와드릴까요?")).toBeInTheDocument();
  });

  it("shows the contextHint as the empty-state text and a scoped placeholder when provided", () => {
    render(
      <MainBriefingChatbot contextHint="다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요." />,
    );
    expect(
      screen.getByText("다른 업무나 질문은 여기에 입력하세요. 영상 제작 요청은 왼쪽 채팅창을 이용해주세요."),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("다른 업무나 질문을 입력하세요")).toBeInTheDocument();
  });
});
