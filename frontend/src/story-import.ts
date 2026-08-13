export type ImportedStoryDraft = {
  name: string;
  keywords: string[];
  answer: string;
};

const HEADER_NAMES = {
  title: ["title", "name", "제목", "스토리 제목"],
  keywords: ["keywords", "keyword", "tags", "키워드", "태그"],
  content: ["content", "body", "본문", "내용", "스토리 내용"],
};

function readHeader(line: string): { kind: "title" | "keywords" | "content"; value: string } | null {
  const match = line.match(/^\s*([^:：]+)\s*[:：]\s*(.*)$/);
  if (!match) return null;
  const key = match[1].trim().toLocaleLowerCase();
  for (const [kind, names] of Object.entries(HEADER_NAMES) as Array<["title" | "keywords" | "content", string[]]>) {
    if (names.some((name) => name.toLocaleLowerCase() === key)) return { kind, value: match[2].trim() };
  }
  return null;
}

export function parseStoryText(text: string, fileName = "story.txt"): ImportedStoryDraft {
  const lines = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n").split("\n");
  const nonEmpty = lines.map((line) => line.trim()).filter(Boolean);
  const titleHeader = lines.map(readHeader).find((header) => header?.kind === "title");
  const keywordHeader = lines.map(readHeader).find((header) => header?.kind === "keywords");
  const contentIndex = lines.findIndex((line) => readHeader(line)?.kind === "content");
  const name = titleHeader?.value || nonEmpty[0] || fileName.replace(/\.txt$/i, "");
  const keywords = keywordHeader?.value.split(",").map((item) => item.trim()).filter(Boolean) ?? [];
  const answer = contentIndex >= 0
    ? lines.slice(contentIndex + 1).join("\n").trim()
    : (titleHeader || keywordHeader ? lines.filter((line) => !readHeader(line)).join("\n").trim() : lines.slice(1).join("\n").trim());
  return { name, keywords, answer };
}
