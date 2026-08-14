import type { UnresolvedScene } from "../resume-utils";
import type { Task } from "./types";

type Props = {
  task: Task | null;
  unresolvedScenes: UnresolvedScene[];
  onUploadScene: (sceneId: string, file: File) => void;
  onRetry: () => void;
};

export function TaskCanvas({ task, unresolvedScenes, onUploadScene, onRetry }: Props) {
  if (!task) {
    return (
      <div className="flex h-full items-center justify-center text-brief-muted" data-testid="canvas-idle">
        브리프를 작성하고 생성 요청을 눌러주세요.
      </div>
    );
  }

  const state = task.status.state;

  if (state === "TASK_STATE_SUBMITTED" || state === "TASK_STATE_WORKING") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3" data-testid="canvas-working">
        <span className="h-10 w-10 animate-spin rounded-full border-4 border-brief-border border-t-brief-accent" />
        <p className="text-brief-text">영상 생성 중...</p>
      </div>
    );
  }

  if (state === "TASK_STATE_INPUT_REQUIRED") {
    return (
      <div className="flex flex-col gap-3" data-testid="canvas-input-required">
        {unresolvedScenes.map((scene) => (
          <div
            key={scene.sceneId}
            className="rounded-[15px] border border-brief-border bg-white p-3"
            data-testid={`scene-card-${scene.sceneId}`}
          >
            <img src={scene.imageUrl} alt={scene.sceneId} className="mb-2 max-h-32 rounded-[8px]" />
            <ul className="mb-2 text-sm text-red-600">
              {scene.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
            <input
              type="file"
              accept="image/*"
              aria-label={`${scene.sceneId} 수정 이미지 업로드`}
              disabled={scene.status === "uploading"}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onUploadScene(scene.sceneId, file);
              }}
            />
            {scene.status === "error" && <p className="text-sm text-red-600">업로드 실패, 다시 시도해주세요.</p>}
          </div>
        ))}
      </div>
    );
  }

  if (state === "TASK_STATE_COMPLETED") {
    const videoUrl = task.artifacts
      ?.flatMap((artifact) => artifact.parts)
      .find((part) => typeof part.data?.output_video_url === "string")?.data?.output_video_url as string | undefined;
    return videoUrl ? (
      <video src={videoUrl} controls className="max-h-full rounded-[15px]" data-testid="canvas-completed" />
    ) : (
      <div data-testid="canvas-completed-no-video">완료되었지만 영상 URL을 찾을 수 없습니다.</div>
    );
  }

  const failureReason = task.status.message?.parts
    .map((part) => part.text)
    .filter(Boolean)
    .join("\n");

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3" data-testid="canvas-error">
      {failureReason && (
        <p className="text-brief-text" data-testid="canvas-error-reason">
          {failureReason}
        </p>
      )}
      <p className="text-brief-text">{state === "TASK_STATE_CANCELED" ? "취소되었습니다." : "생성에 실패했습니다."}</p>
      <button type="button" onClick={onRetry} className="rounded-[8px] bg-brief-accent px-3 py-2 text-sm text-white">
        다시 시도
      </button>
    </div>
  );
}
