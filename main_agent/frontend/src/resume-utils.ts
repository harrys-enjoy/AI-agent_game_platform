export type UnresolvedSceneStatus = "pending" | "uploading" | "error";
export type RawUnresolvedScene = { sceneId: string; imageUrl: string; issues: string[] };
export type UnresolvedScene = RawUnresolvedScene & { status: UnresolvedSceneStatus };
export type ResumeResult = {
  scene_id: string;
  resolved: boolean;
  remaining_unresolved: RawUnresolvedScene[];
  output_video_url: string | null;
};

export function buildUnresolvedScenes(rawScenes: RawUnresolvedScene[]): UnresolvedScene[] {
  return rawScenes.map((scene) => ({ ...scene, status: "pending" }));
}

export function markSceneStatus(scenes: UnresolvedScene[], sceneId: string, status: UnresolvedSceneStatus): UnresolvedScene[] {
  return scenes.map((scene) => (scene.sceneId === sceneId ? { ...scene, status } : scene));
}

export function mergeResumeResult(previous: UnresolvedScene[], result: ResumeResult): UnresolvedScene[] {
  return result.remaining_unresolved.map((scene) => ({
    ...scene,
    status: previous.find((item) => item.sceneId === scene.sceneId)?.status ?? "pending",
  }));
}

export function buildResumeFormData(file: File): FormData {
  const formData = new FormData();
  formData.append("file", file);
  return formData;
}

export function finalVideoMessageText(outputVideoUrl: string): string {
  return `모든 씬이 해결되었습니다. 완성된 영상: ${outputVideoUrl}`;
}
