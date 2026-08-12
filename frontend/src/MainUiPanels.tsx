import type { UiVariant } from "./ui-variant";
import { quickActions } from "./ui-variant";

export function PoliciesPanel() {
  return <section className="policies-card"><div className="policies-heading"><div><p className="eyebrow">MAIN AGENT / POLICIES</p><h2>Company Policies</h2><p>팀에서 자주 확인하는 사규와 운영 기준을 한곳에서 확인하세요.</p></div><input aria-label="Search company policies" placeholder="Search policies" /></div><div className="policy-grid"><article><span>01</span><h3>근무 및 휴가</h3><p>근무시간, 휴가, 재택근무 기준</p></article><article><span>02</span><h3>보안 및 개인정보</h3><p>정보보호와 데이터 취급 기준</p></article><article><span>03</span><h3>업무 운영</h3><p>회의, 승인, 협업 운영 기준</p></article><article><span>04</span><h3>복지 및 지원</h3><p>구성원 지원 제도와 이용 안내</p></article></div></section>;
}

export function QuickActions({ variant, currentChat, onSelect }: { variant: UiVariant; currentChat: string; onSelect: (prompt: string) => void }) {
  if (variant !== "updated" || currentChat !== "Workmate AI") return null;
  return <div className="quick-actions" aria-label="Workmate AI quick actions">{quickActions.map((action) => <button type="button" className="quick-action" key={action.id} onClick={() => onSelect(action.prompt)}><span className="quick-action-icon">↗</span><span><strong>{action.label}</strong><small>{action.prompt}</small></span></button>)}</div>;
}

export function TaskQuickActions({ variant, onSelect }: { variant: UiVariant; onSelect: (prompt: string) => void }) {
  if (variant !== "updated") return null;
  return <nav className="task-quick-actions" aria-label="업무 빠른 메뉴">{quickActions.map((action) => <button type="button" key={action.id} onClick={() => onSelect(action.prompt)}>{action.label}</button>)}</nav>;
}

export function ReportPanel({ kind }: { kind: "briefing" | "weekly" }) {
  const weekly = kind === "weekly";
  return <section className="report-panel"><div className="report-panel-heading"><div><p className="eyebrow">MAIN AGENT / {weekly ? "WEEKLY REPORT" : "TODAY BRIEFING"}</p><h2>{weekly ? "주간 업무 보고" : "오늘 브리핑"}</h2><p>{weekly ? "이번 주 업무 진행 상황과 다음 주 우선순위를 정리합니다." : "오늘 예정된 업무와 중요한 진행 상황을 한눈에 확인합니다."}</p></div><span className="report-date">{weekly ? "이번 주" : "오늘"}</span></div><div className="report-summary"><article><span>{weekly ? "완료한 업무" : "오늘의 업무"}</span><strong>{weekly ? "12건" : "5건"}</strong></article><article><span>{weekly ? "진행 중인 업무" : "우선 확인"}</span><strong>{weekly ? "7건" : "2건"}</strong></article><article><span>{weekly ? "다음 주 계획" : "회의 일정"}</span><strong>{weekly ? "4건" : "3건"}</strong></article></div><div className="report-list"><h3>{weekly ? "이번 주 주요 업무" : "오늘의 주요 업무"}</h3><p>업무 세부 내용과 상태는 프로젝트 작업 목록에서 계속 관리할 수 있습니다.</p><p>필요한 내용은 Workmate AI 채팅에서 별도로 요청할 수 있습니다.</p></div></section>;
}

export function UpdatedReportNav({ variant, activeSection, onSelect }: { variant: UiVariant; activeSection: string; onSelect: (section: string) => void }) {
  if (variant !== "updated") return null;
  return <div className="updated-report-nav"><span>업무 보고</span><button className={activeSection === "Today Briefing" ? "active" : ""} type="button" onClick={() => onSelect("Today Briefing")}>오늘 브리핑</button><button className={activeSection === "Weekly Report" ? "active" : ""} type="button" onClick={() => onSelect("Weekly Report")}>주간 업무 보고</button></div>;
}
