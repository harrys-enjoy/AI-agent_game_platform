import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ComposerTabs } from "./ComposerTabs";
import { ChatComposer } from "./ChatComposer";
import { FormComposer } from "./FormComposer";

describe("ComposerTabs", () => {
  afterEach(() => {
    cleanup();
  });
  it("shows the chat panel by default and switches to the form panel on click", async () => {
    render(<ComposerTabs chat={<div>채팅 패널</div>} form={<div>폼 패널</div>} />);

    expect(screen.getByText("채팅 패널")).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "폼" }));
    expect(screen.getByText("폼 패널")).toBeVisible();
  });

  it("keeps each tab's draft state when switching away and back", async () => {
    render(
      <ComposerTabs
        chat={<ChatComposer disabled={false} onSubmit={vi.fn()} />}
        form={<FormComposer disabled={false} onSubmit={vi.fn()} />}
      />,
    );

    await userEvent.type(screen.getByLabelText("영상 브리프"), "채팅 탭에 남긴 초안");
    await userEvent.click(screen.getByRole("tab", { name: "폼" }));
    await userEvent.type(screen.getByLabelText("브리프"), "폼 탭에 남긴 초안");
    await userEvent.click(screen.getByRole("tab", { name: "채팅" }));

    expect(screen.getByLabelText("영상 브리프")).toHaveValue("채팅 탭에 남긴 초안");
    await userEvent.click(screen.getByRole("tab", { name: "폼" }));
    expect(screen.getByLabelText("브리프")).toHaveValue("폼 탭에 남긴 초안");
  });
});
