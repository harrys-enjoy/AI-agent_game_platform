// frontend/src/video-agent/types.ts
import type { RawUnresolvedScene } from "../resume-utils";

export type TaskState =
  | "TASK_STATE_SUBMITTED"
  | "TASK_STATE_WORKING"
  | "TASK_STATE_INPUT_REQUIRED"
  | "TASK_STATE_AUTH_REQUIRED"
  | "TASK_STATE_COMPLETED"
  | "TASK_STATE_FAILED"
  | "TASK_STATE_CANCELED"
  | "TASK_STATE_REJECTED";

export type ArtifactPart = { text?: string; data?: Record<string, unknown>; mediaType?: string };
export type Artifact = { artifactId: string; name: string; parts: ArtifactPart[] };
export type TaskStatus = { state: TaskState; message?: { parts: ArtifactPart[] }; unresolvedScenes?: RawUnresolvedScene[] };
export type Task = {
  id: string;
  contextId: string;
  status: TaskStatus;
  artifacts?: Artifact[];
  brief?: string | null;
  createdAt?: string;
};
export type MessageSendResponse = { task: Task } | { message: { parts: ArtifactPart[] } };
export type TaskListResponse = { tasks: Task[]; has_more: boolean };
export type TaskDetail = { task_id: string; brief: string | null; project: Record<string, unknown> | null };
export type VeoUsage = { used: number; limit: number; resetsAt: string | null };
