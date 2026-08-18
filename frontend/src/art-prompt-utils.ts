export type ArtPrompt = Record<string, unknown>;

export function formatArtPromptJson(prompt: ArtPrompt): string {
  return JSON.stringify(prompt, null, 2);
}

export function parseArtPromptJson(json: string): ArtPrompt | null {
  try {
    const parsed = JSON.parse(json);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as ArtPrompt : null;
  } catch {
    return null;
  }
}

export function extractArtPrompt(answer: string): ArtPrompt | null {
  const jsonStart = answer.indexOf("{");
  if (jsonStart < 0) return null;
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (let index = jsonStart; index < answer.length; index += 1) {
    const character = answer[index];
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
      continue;
    }
    if (character === '"') quoted = true;
    else if (character === "{") depth += 1;
    else if (character === "}") {
      depth -= 1;
      if (depth !== 0) continue;
      try {
        const parsed = JSON.parse(answer.slice(jsonStart, index + 1));
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
        const candidate = parsed as ArtPrompt;
        const hasStory = "story" in candidate || "스토리 맥락" in candidate;
        const hasCharacter = "character" in candidate || "인물상" in candidate;
        const hasContext = "context" in candidate || "갈등" in candidate;
        return hasStory && hasCharacter && hasContext ? candidate : null;
      } catch {
        return null;
      }
    }
  }
  return null;
}

function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return Object.entries(value as ArtPrompt).map(([key, item]) => `${key}: ${displayValue(item)}`).join(" · ");
  return String(value ?? "확인 필요");
}

export function formatArtPromptForChat(prompt: ArtPrompt | null): string {
  if (!prompt) return "아트 프롬프트를 해석하지 못했습니다.";
  const lines = [
    "아트 프롬프트 초안",
    "",
    `스토리 맥락: ${displayValue(prompt.story ?? prompt["스토리 맥락"] ?? "확인 필요")}`,
    `인물상: ${displayValue(prompt.character ?? prompt["인물상"] ?? "확인 필요")}`,
    `역할·갈등: ${displayValue(prompt.context ?? prompt["갈등"] ?? "확인 필요")}`,
  ];
  if (prompt.nearby) lines.push(`주변 인물·세력: ${displayValue(prompt.nearby)}`);
  if (prompt.prompt) lines.push(`연출 방향: ${displayValue(prompt.prompt)}`);
  if (prompt["카메라 구도"]) lines.push(`카메라: ${displayValue(prompt["카메라 구도"])}`);
  if (prompt["조명"]) lines.push(`조명·분위기: ${displayValue(prompt["조명"])}`);
  return lines.join("\n");
}
