import { useState } from "react";
import { assigneeOptions, AssigneeAssignments, AssigneeRole, defaultAssignments, findAssignee, roleOptions } from "./assignee";

export function AssigneeSwitcher({ name, onChange, assignments, onSaveAssignments }: { name: string; onChange: (name: string) => void; assignments: AssigneeAssignments; onSaveAssignments: (assignments: AssigneeAssignments) => void }) {
  const selected = findAssignee(name);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<AssigneeAssignments>(assignments);
  function updateRole(role: AssigneeRole, value: string) { setDraft((current) => ({ ...current, [role]: value })); }
  function saveSettings() { onSaveAssignments(draft); setIsSettingsOpen(false); }
  return <div className={`assignee-switcher ${isSettingsOpen ? "settings-open" : ""}`}>
    <label htmlFor="assignee-name">담당자</label><select id="assignee-name" value={selected.name} onChange={(event) => onChange(event.target.value)}>{assigneeOptions.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select><span>{selected.role}</span>
    <button className="assignee-settings-toggle" type="button" onClick={() => setIsSettingsOpen((open) => !open)}>{isSettingsOpen ? "담당자 설정 닫기" : "담당자 설정"}</button>
    {isSettingsOpen && <div className="assignee-settings"><strong>담당자 설정</strong>{roleOptions.map((role) => <label key={role}><select aria-label={`${role} 업무`} value={role}><option value={role}>{role}</option></select><select aria-label={`${role} 담당자`} value={draft[role]} onChange={(event) => updateRole(role, event.target.value)}>{assigneeOptions.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>)}<button className="assignee-settings-save" type="button" onClick={saveSettings}>저장</button><button className="assignee-settings-reset" type="button" onClick={() => { setDraft(defaultAssignments); onSaveAssignments(defaultAssignments); }}>기본값</button></div>}
  </div>;
}
