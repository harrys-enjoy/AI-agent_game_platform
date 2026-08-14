import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { ComposerTabs } from "./ComposerTabs";

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
});
