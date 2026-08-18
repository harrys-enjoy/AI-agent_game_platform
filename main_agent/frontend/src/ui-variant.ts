export type UiVariant = "legacy" | "updated";

export const quickActions = [
  { id: "tasks", label: "할 일 관리", prompt: "오늘 할 일과 우선순위를 정리해줘" },
  { id: "recording", label: "회의 녹음", prompt: "회의 녹음을 시작하고 회의 내용을 정리해줘" },
  { id: "meetings", label: "회의 관리", prompt: "이번 주 회의 일정을 관리해줘" },
  { id: "minutes", label: "회의록 검색", prompt: "회의록에서 필요한 내용을 검색해줘" },
] as const;

export function readUiVariant(value: string | null): UiVariant {
  return value === "updated" ? "updated" : "legacy";
}
