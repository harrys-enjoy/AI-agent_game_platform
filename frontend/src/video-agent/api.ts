import { buildResumeFormData, type ResumeResult } from "../resume-utils";
import type { MessageSendResponse, Task } from "./types";

const API_BASE_URL = "http://127.0.0.1:8000";

export async function createVideoAgentTask(message: string): Promise<MessageSendResponse> {
  const response = await fetch(`${API_BASE_URL}/api/video-agent/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) throw new Error(`video-agent task create failed: HTTP ${response.status}`);
  return response.json();
}

export class VideoAgentTaskNotFoundError extends Error {}

export async function getVideoAgentTask(taskId: string): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/video-agent/tasks/${encodeURIComponent(taskId)}`);
  if (response.status === 404) throw new VideoAgentTaskNotFoundError(`video-agent task not found: ${taskId}`);
  if (!response.ok) throw new Error(`video-agent task fetch failed: HTTP ${response.status}`);
  const payload = await response.json();
  return payload.task as Task;
}

export async function cancelVideoAgentTask(taskId: string): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/video-agent/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
  if (!response.ok) throw new Error(`video-agent task cancel failed: HTTP ${response.status}`);
  const payload = await response.json();
  return payload.task as Task;
}

export async function resumeVideoAgentScene(taskId: string, sceneId: string, file: File): Promise<ResumeResult> {
  const response = await fetch(
    `${API_BASE_URL}/api/video-agent/tasks/${encodeURIComponent(taskId)}/scenes/${encodeURIComponent(sceneId)}/resume`,
    { method: "POST", body: buildResumeFormData(file) },
  );
  if (!response.ok) throw new Error(`video-agent scene resume failed: HTTP ${response.status}`);
  return response.json();
}
