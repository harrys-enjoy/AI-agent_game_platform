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
  });

  it("renders VideoAgentPage instead of the generic chat panel when Video Generation is selected", async () => {
    render(<App />);

    await userEvent.click(screen.getByText("Video Generation"));

    expect(await screen.findByLabelText("영상 브리프")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Type a message...")).not.toBeInTheDocument();
  });
});
