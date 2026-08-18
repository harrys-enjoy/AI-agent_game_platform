const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp"]);
const CODE_EXTENSIONS = new Set(["js", "jsx", "ts", "tsx", "py", "java", "cs", "cpp", "c", "go", "rs", "json", "yaml", "yml", "md", "html", "css", "scss", "sql", "sh"]);

export type PreviewKind = "image" | "code" | "unsupported";

export function getPreviewKind(fileName: string): PreviewKind {
  const extension = fileName.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (CODE_EXTENSIONS.has(extension)) return "code";
  return "unsupported";
}

export function getLanguageLabel(fileName: string): string {
  const extension = fileName.split(".").pop()?.toUpperCase();
  return extension && extension !== fileName.toUpperCase() ? extension : "TEXT";
}
