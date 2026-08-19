// ProposalCard가 쓰는 승인/무시 호출 경계 — email/calendar 라우팅과
// Idempotency-Key 조립을 한 곳에만 둔다. `workmate-ui/lib/proposal-review.ts`에서
// 그대로 이식(19번 문서 7단계).

import { proposalsApi, type WorkmateConfig } from "./api";
import type { ProposalReviewResult, TaskProposal } from "./types";

export type ProposalTaskInput = {
  title: string;
  assignee_user_id: string;
  due_at: string | null;
  priority_hint: number | null;
};

export function defaultTaskInput(proposal: TaskProposal): ProposalTaskInput {
  return {
    title: proposal.title,
    assignee_user_id: proposal.assignee_user_id,
    due_at: proposal.due_at,
    priority_hint: proposal.priority_hint,
  };
}

export async function reviewProposal(
  config: WorkmateConfig,
  proposal: TaskProposal,
  decision: "approve" | "ignore",
  task: ProposalTaskInput | undefined,
  allowSimilarDuplicate = false,
): Promise<ProposalReviewResult> {
  const idempotencyKey = `${proposal.proposal_id}-${decision}-${Date.now()}`;
  if (proposal.source_type === "email") {
    return proposalsApi.reviewEmail(config, { message_id: proposal.source_id, decision, task, allow_similar_duplicate: allowSimilarDuplicate }, idempotencyKey);
  }
  const metadata = (proposal.metadata as Record<string, unknown> | null) ?? {};
  return proposalsApi.reviewCalendar(
    config,
    {
      calendar_id: String(metadata.calendar_id ?? ""),
      event_id: String(metadata.event_id ?? ""),
      decision,
      task,
      allow_similar_duplicate: allowSimilarDuplicate,
    },
    idempotencyKey,
  );
}
