import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";
import { FormComposer } from "./FormComposer";

describe("FormComposer", () => {
  afterEach(() => cleanup());
  it("composes the structured fields into one message on submit", async () => {
    const onSubmit = vi.fn();
    render(<FormComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("브리프"), "할로윈 이벤트");
    await userEvent.type(screen.getByLabelText("길이(초)"), "20");
    await userEvent.selectOptions(screen.getByLabelText("프리셋"), "이벤트");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    const message = onSubmit.mock.calls[0][0] as string;
    expect(message).toContain("할로윈 이벤트");
    expect(message).toMatch(/20\s*초/);
    expect(message).toContain("이벤트");
  });

  it("does not submit when the brief is shorter than 5 characters", async () => {
    const onSubmit = vi.fn();
    render(<FormComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("브리프"), "짧음");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables every field while a task is busy", () => {
    render(<FormComposer disabled={true} onSubmit={vi.fn()} />);

    expect(screen.getByLabelText("브리프")).toBeDisabled();
    expect(screen.getByLabelText("길이(초)")).toBeDisabled();
    expect(screen.getByLabelText("프리셋")).toBeDisabled();
    expect(screen.getByLabelText("씬 종류")).toBeDisabled();
    expect(screen.getByLabelText("예산(달러)")).toBeDisabled();
    expect(screen.getByRole("button", { name: "생성 요청" })).toBeDisabled();
  });

  it("blocks submit and warns when duration exceeds the 30s cap", async () => {
    const onSubmit = vi.fn();
    render(<FormComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("브리프"), "할로윈 이벤트");
    await userEvent.type(screen.getByLabelText("길이(초)"), "45");

    expect(screen.getByTestId("duration-cap-warning")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "생성 요청" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("blocks submit and warns when duration is under the 16s floor", async () => {
    const onSubmit = vi.fn();
    render(<FormComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("브리프"), "할로윈 이벤트");
    await userEvent.type(screen.getByLabelText("길이(초)"), "12");

    expect(screen.getByTestId("duration-min-warning")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "생성 요청" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects non-digit keystrokes in the duration field", async () => {
    render(<FormComposer disabled={false} onSubmit={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("길이(초)"), "ab15cd");
    expect(screen.getByLabelText("길이(초)")).toHaveValue("15");
  });

  it("warns (without blocking submit) when budget exceeds the $10 cap", async () => {
    const onSubmit = vi.fn();
    render(<FormComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("브리프"), "할로윈 이벤트");
    await userEvent.type(screen.getByLabelText("예산(달러)"), "50");

    expect(screen.getByTestId("budget-cap-warning")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "생성 요청" })).toBeEnabled();
  });
});
