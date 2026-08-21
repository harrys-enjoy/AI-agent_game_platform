import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";
import { ChatComposer } from "./ChatComposer";

describe("ChatComposer", () => {
  afterEach(() => cleanup());
  it("submits the trimmed message", async () => {
    const onSubmit = vi.fn();
    render(<ChatComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("영상 브리프"), "  할로윈 이벤트 영상 15초  ");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    expect(onSubmit).toHaveBeenCalledWith("할로윈 이벤트 영상 15초");
  });

  it("does not submit text shorter than 5 characters", async () => {
    const onSubmit = vi.fn();
    render(<ChatComposer disabled={false} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("영상 브리프"), "짧음");
    await userEvent.click(screen.getByRole("button", { name: "생성 요청" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables the submit button while a task is busy", () => {
    render(<ChatComposer disabled={true} onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "생성 요청" })).toBeDisabled();
  });

  it("disables the brief textarea while a task is busy", () => {
    render(<ChatComposer disabled={true} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("영상 브리프")).toBeDisabled();
  });

  it("states the real duration and budget limits in the placeholder", () => {
    render(<ChatComposer disabled={false} onSubmit={vi.fn()} />);
    expect(
      screen.getByPlaceholderText(
        "무엇을 홍보할지 구체적으로 적어주세요 (캐릭터/이벤트/게임 장면 등, 16~30초, 예산 $10 이하). 예: 할로윈 신규 캐릭터 '루멘' 공개 이벤트, 20초로",
      ),
    ).toBeInTheDocument();
  });
});
