import { useEffect, useRef, useState } from "react";
import { deleteVideoAgentTask, listVideoAgentTasks } from "./api";
import { LABELS } from "./StatusBadge";
import { VideoDetailModal } from "./VideoDetailModal";
import type { Task } from "./types";

const PAGE_SIZE = 20;
const CONFIRM_TIMEOUT_MS = 3000;

function outputVideoUrl(task: Task): string | undefined {
  return task.artifacts
    ?.flatMap((artifact) => artifact.parts)
    .find((part) => typeof part.data?.output_video_url === "string")?.data?.output_video_url as string | undefined;
}

export function VideoGallery({ assignee, refreshKey }: { assignee?: string; refreshKey?: unknown }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openTask, setOpenTask] = useState<Task | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const confirmTimeoutRef = useRef<number | null>(null);

  // New assignee, or a task just changed state (e.g. finished) - start over from page 1.
  useEffect(() => {
    setError(null);
    if (!assignee) {
      setTasks([]);
      setHasMore(false);
      return;
    }
    let cancelled = false;
    listVideoAgentTasks(assignee, PAGE_SIZE, 0)
      .then((result) => {
        if (cancelled) return;
        setTasks(result.tasks);
        setHasMore(result.has_more);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "영상 목록을 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignee, refreshKey]);

  useEffect(() => {
    return () => {
      if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current);
    };
  }, []);

  async function loadMore() {
    if (!assignee || !tasks) return;
    setLoadingMore(true);
    try {
      const result = await listVideoAgentTasks(assignee, PAGE_SIZE, tasks.length);
      setTasks((previous) => [...(previous ?? []), ...result.tasks]);
      setHasMore(result.has_more);
    } catch (err) {
      setError(err instanceof Error ? err.message : "영상 목록을 불러오지 못했습니다.");
    } finally {
      setLoadingMore(false);
    }
  }

  function armDelete(taskId: string) {
    if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current);
    setConfirmDeleteId(taskId);
    confirmTimeoutRef.current = window.setTimeout(() => setConfirmDeleteId(null), CONFIRM_TIMEOUT_MS);
  }

  async function performDelete(taskId: string) {
    if (confirmTimeoutRef.current) window.clearTimeout(confirmTimeoutRef.current);
    setConfirmDeleteId(null);
    try {
      await deleteVideoAgentTask(taskId);
      setTasks((previous) => previous?.filter((task) => task.id !== taskId) ?? previous);
      setOpenTask((current) => (current?.id === taskId ? null : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : "영상 삭제에 실패했습니다.");
    }
  }

  function handleDeleteClick(event: React.MouseEvent, taskId: string) {
    event.stopPropagation();
    if (confirmDeleteId === taskId) {
      void performDelete(taskId);
    } else {
      armDelete(taskId);
    }
  }

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
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" data-testid="video-gallery-grid">
            {tasks.map((task) => {
              const videoUrl = outputVideoUrl(task);
              const confirming = confirmDeleteId === task.id;
              return (
                <div
                  key={task.id}
                  className="group relative flex flex-col gap-2 rounded-[10px] border border-brief-border p-2"
                  data-testid={`video-gallery-item-${task.id}`}
                >
                  <button
                    type="button"
                    onClick={() => setOpenTask(task)}
                    className="flex flex-col gap-2 text-left"
                    data-testid={`video-gallery-open-${task.id}`}
                  >
                    {videoUrl ? (
                      <video src={videoUrl} className="aspect-video w-full rounded-[8px] bg-black" muted />
                    ) : (
                      <div className="flex aspect-video w-full items-center justify-center rounded-[8px] bg-brief-bg text-xs text-brief-muted">
                        {LABELS[task.status.state]}
                      </div>
                    )}
                    <span className="truncate text-xs text-brief-muted">{task.brief || task.id}</span>
                  </button>
                  <button
                    type="button"
                    onClick={(event) => handleDeleteClick(event, task.id)}
                    className={`absolute right-1.5 top-1.5 rounded-full px-1.5 py-0.5 text-xs font-bold text-white transition-opacity ${
                      confirming ? "bg-red-600 opacity-100" : "bg-black/60 opacity-0 group-hover:opacity-100"
                    }`}
                    aria-label={confirming ? "삭제 확인" : "영상 삭제"}
                    data-testid={`video-gallery-delete-${task.id}`}
                  >
                    {confirming ? "삭제?" : "✕"}
                  </button>
                </div>
              );
            })}
          </div>
          {hasMore && (
            <div className="mt-3 flex justify-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-[8px] border border-brief-border px-4 py-2 text-sm text-brief-text"
                data-testid="video-gallery-load-more"
              >
                {loadingMore ? "불러오는 중..." : "더 보기"}
              </button>
            </div>
          )}
        </>
      )}
      <VideoDetailModal task={openTask} onClose={() => setOpenTask(null)} onDelete={performDelete} />
    </section>
  );
}
