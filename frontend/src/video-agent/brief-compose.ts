export type StructuredBriefFields = {
  brief: string;
  durationSec?: number;
  preset?: "이벤트" | "공개" | "커뮤니티";
  sceneType?: "인게임" | "스튜디오";
  maxBudgetUsd?: number;
};

export function composeStructuredBrief(fields: StructuredBriefFields): string {
  const parts = [fields.brief.trim()];
  if (fields.durationSec) parts.push(`${fields.durationSec}초로`);
  if (fields.preset) parts.push(`${fields.preset} 프리셋`);
  if (fields.sceneType) parts.push(`${fields.sceneType} 씬으로`);
  if (fields.maxBudgetUsd) parts.push(`예산 ${fields.maxBudgetUsd}달러로`);
  return `${parts.join(", ")} 만들어줘`;
}
