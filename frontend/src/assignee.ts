export const roleOptions = ["Workmate 담당자", "Video 담당자", "Develop 담당자", "Game Q&A 담당자"] as const;
export type AssigneeRole = (typeof roleOptions)[number];
export const assigneeOptions = [
  { name: "서선정", role: "Workmate 담당자", chat: "Workmate AI" },
  { name: "배동우", role: "Video 담당자", chat: "Video Generation" },
  { name: "이승현", role: "Develop 담당자", chat: "Development Assistant" },
  { name: "변해훈", role: "Game Q&A 담당자", chat: "Game Q&A" },
] as const;
export type Assignee = (typeof assigneeOptions)[number];
export type AssigneeAssignments = Record<AssigneeRole, string>;
export const defaultAssignments: AssigneeAssignments = { "Workmate 담당자": "서선정", "Video 담당자": "배동우", "Develop 담당자": "이승현", "Game Q&A 담당자": "변해훈" };
export function findAssignee(name: string): Assignee { return assigneeOptions.find((item) => item.name === name) ?? assigneeOptions[0]; }
