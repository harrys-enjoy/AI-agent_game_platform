import { cleanup, render, screen } from "@testing-library/react";
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

  it("routes away from Video Generation when the routing chatbot matches a different agent", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Video Generation"));
    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();

    const chatbotInput = screen.getByPlaceholderText("Type a message...");
    await userEvent.type(chatbotInput, "코드 버그 확인해줘");
    const chatbotSubmit = chatbotInput.closest("form")?.querySelector("button[type='submit']") as HTMLButtonElement;
    await userEvent.click(chatbotSubmit);

    expect(await screen.findByPlaceholderText("Type a message...")).toBeInTheDocument();
    expect(screen.queryByLabelText("영상 브리프")).not.toBeInTheDocument();
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
});
