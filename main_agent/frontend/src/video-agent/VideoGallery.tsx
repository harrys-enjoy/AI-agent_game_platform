import { useEffect, useState } from "react";
import { listVideoAgentTasks } from "./api";
import { LABELS } from "./StatusBadge";
import type { Task } from "./types";

function outputVideoUrl(task: Task): string | undefined {
  return task.artifacts
    ?.flatMap((artifact) => artifact.parts)
    .find((part) => typeof part.data?.output_video_url === "string")?.data?.output_video_url as string | undefined;
}

export function VideoGallery({ assignee, refreshKey }: { assignee?: string; refreshKey?: unknown }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!assignee) {
      setTasks([]);
      return;
    }
    let cancelled = false;
    listVideoAgentTasks(assignee)
      .then((result) => {
        if (!cancelled) setTasks(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "영상 목록을 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [assignee, refreshKey]);

  return (
    <section className="mt-4 rounded-[15px] border border-brief-border bg-white p-4" data-testid="video-gallery">
      <h2 className="mb-3 text-base font-semibold text-brief-text">내 영상</h2>
      {error && (
        <p className="rounded bg-red-50 p-2 text-sm text-red-700" data-testid="video-gallery-error">
          {error}
        </p>
      )}
      {!error && tasks === null && (
        <div className="flex h-24 items-center justify-center text-brief-muted" data-testid="video-gallery-loading">
          불러오는 중...
        </div>
      )}
      {!error && tasks !== null && tasks.length === 0 && (
        <div className="flex h-24 items-center justify-center text-brief-muted" data-testid="video-gallery-empty">
          생성한 영상이 없습니다. 영상을 생성하면 여기에 표시됩니다.
        </div>
      )}
      {!error && tasks !== null && tasks.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" data-testid="video-gallery-grid">
          {tasks.map((task) => {
            const videoUrl = outputVideoUrl(task);
            return (
              <div
                key={task.id}
                className="flex flex-col gap-2 rounded-[10px] border border-brief-border p-2"
                data-testid={`video-gallery-item-${task.id}`}
              >
                {videoUrl ? (
                  <video src={videoUrl} controls className="aspect-video w-full rounded-[8px] bg-black" />
                ) : (
                  <div className="flex aspect-video w-full items-center justify-center rounded-[8px] bg-brief-bg text-xs text-brief-muted">
                    {LABELS[task.status.state]}
                  </div>
                )}
                <span className="truncate text-xs text-brief-muted">{task.id}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
