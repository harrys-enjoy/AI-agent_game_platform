import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { getLanguageLabel, getPreviewKind, PreviewKind } from "./preview-utils";

type PreviewFile = { id: string; file: File; kind: PreviewKind; content?: string; objectUrl?: string; error?: string };

function createPreviewFile(file: File): PreviewFile {
  const kind = getPreviewKind(file.name);
  return { id: `${file.name}-${file.lastModified}-${file.size}`, file, kind, objectUrl: kind === "image" ? URL.createObjectURL(file) : undefined };
}

export default function PreviewPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const [files, setFiles] = useState<PreviewFile[]>([]);
  const [activeId, setActiveId] = useState<string>();
  const filesRef = useRef<PreviewFile[]>([]);
  const activeFile = useMemo(() => files.find((item) => item.id === activeId) ?? files[0], [activeId, files]);

  useEffect(() => { filesRef.current = files; }, [files]);
  useEffect(() => () => filesRef.current.forEach((item) => item.objectUrl && URL.revokeObjectURL(item.objectUrl)), []);

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    if (!selected.length) return;
    const loadedFiles = await Promise.all(selected.map(async (file) => {
      const item = createPreviewFile(file);
      if (item.kind !== "code") return item;
      try { return { ...item, content: await file.text() }; }
      catch { return { ...item, error: "파일 내용을 읽을 수 없습니다." }; }
    }));
    setFiles((current) => [...current, ...loadedFiles.filter((item) => !current.some((existing) => existing.id === item.id))]);
    setActiveId(loadedFiles[0]?.id);
    setIsOpen(true);
    event.target.value = "";
  }

  return <section className={`preview-panel ${isOpen ? "is-open" : "is-closed"}`}>
    <div className="preview-header"><div><span className="preview-kicker">ADD CODE</span><h2>Workspace Preview</h2></div><div className="preview-actions"><label className="file-button">+ Add file<input type="file" multiple onChange={handleFiles} accept=".png,.jpg,.jpeg,.gif,.webp,.js,.jsx,.ts,.tsx,.py,.java,.cs,.cpp,.c,.go,.rs,.json,.yaml,.yml,.md,.html,.css,.scss,.sql,.sh" /></label><button className="collapse-button" type="button" onClick={() => setIsOpen((value) => !value)} aria-expanded={isOpen}>{isOpen ? "축소 ˄" : "열기 ˅"}</button></div></div>
    {isOpen && <div className="preview-body"><div className="preview-toolbar"><div className="file-tabs" role="list" aria-label="선택한 파일">{files.map((item) => <button className={`file-tab ${activeFile?.id === item.id ? "active" : ""}`} key={item.id} type="button" onClick={() => setActiveId(item.id)}>{item.file.name}</button>)}</div><div className="view-tabs" aria-label="미리보기 형식"><span className={`view-tab ${activeFile?.kind === "image" ? "active" : ""}`}>Image</span><span className={`view-tab ${activeFile?.kind === "code" ? "active" : ""}`}>Code</span></div></div><div className="preview-canvas">{!activeFile && <div className="preview-empty"><strong>파일을 추가해 주세요</strong><span>이미지 또는 코드 파일을 선택하면 이곳에서 확인할 수 있습니다.</span></div>}{activeFile?.kind === "image" && activeFile.objectUrl && <img className="image-preview" src={activeFile.objectUrl} alt={activeFile.file.name} />}{activeFile?.kind === "code" && <div className="code-preview"><div className="code-meta">{activeFile.file.name}<span>{getLanguageLabel(activeFile.file.name)}</span></div><pre>{activeFile.error ?? activeFile.content ?? "파일을 읽는 중입니다..."}</pre></div>}{activeFile?.kind === "unsupported" && <div className="preview-empty"><strong>미리보기를 지원하지 않는 파일입니다</strong><span>이미지 또는 코드 파일을 선택해 주세요.</span></div>}</div></div>}
  </section>;
}
