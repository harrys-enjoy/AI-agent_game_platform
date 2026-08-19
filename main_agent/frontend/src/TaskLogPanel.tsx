import { useEffect, useRef, useState } from "react";

const API_BASE_URL = "http://127.0.0.1:8000";
const AGENTS = ["Workmate AI", "Video Generation", "Development Assistant", "Game Q&A"];
type TaskLog = { log_id: string; recorded_at: string; agent: string; task_name: string; owner: string; status: string; result_summary: string };

function localDate() {
  const date = new Date();
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export default function TaskLogPanel() {
  const [workDate, setWorkDate] = useState(localDate);
  const [owner, setOwner] = useState("");
  const [agent, setAgent] = useState("");
  const [resetId, setResetId] = useState("");
  const [owners, setOwners] = useState<string[]>([]);
  const [items, setItems] = useState<TaskLog[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  async function load(reset = false, resetIdOverride?: string) {
    if (loading || (!hasMore && !reset)) return;
    setLoading(true);
    const nextOffset = reset ? 0 : offset;
    const query = new URLSearchParams({ work_date: workDate, offset: String(nextOffset), limit: "30" });
    if (owner) query.set("owner", owner);
    if (agent) query.set("agent", agent);
    const selectedResetId = resetIdOverride ?? resetId;
    if (selectedResetId) query.set("reset_id", selectedResetId);
    try {
      const response = await fetch(`${API_BASE_URL}/api/policies/task-logs?${query}`);
      if (!response.ok) {
        if (reset) { setItems([]); setHasMore(false); }
        return;
      }
      const data = await response.json() as { items: TaskLog[]; next_offset: number | null };
      const nextItems = Array.isArray(data.items) ? data.items : [];
      setItems((current) => reset ? nextItems : [...current, ...nextItems]);
      setOffset(data.next_offset ?? nextOffset);
      setHasMore(data.next_offset !== null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/policies/task-log-owners`).then((response) => response.ok ? response.json() : []).then((data) => setOwners(Array.isArray(data) ? data : [])).catch(() => setOwners([]));
  }, []);

  useEffect(() => { setResetId(""); setItems([]); setOffset(0); setHasMore(true); void load(true, ""); }, [workDate, owner, agent]);

  function handleScroll() {
    const element = scrollRef.current;
    if (element && element.scrollTop + element.clientHeight >= element.scrollHeight - 80) void load();
  }

  async function resetLog() {
    const response = await fetch(`${API_BASE_URL}/api/policies/task-logs/reset?work_date=${workDate}`, { method: "POST" });
    const reset = await response.json() as { reset_id: string };
    setResetId(reset.reset_id); setItems([]); setOffset(0); setHasMore(true); void load(true, reset.reset_id);
  }

  return <section className="task-log-card" aria-label="Agent 작업 이력">
    <div className="task-log-heading"><div><p className="eyebrow">MAIN AGENT / POLICIES</p><h2>Agent 작업 이력</h2><p>담당자가 수행한 작업을 일 단위로 누적 기록합니다. 기존 기록은 수정하거나 삭제하지 않습니다.</p></div><button className="task-log-reset" type="button" onClick={() => void resetLog()}>Reset</button></div>
    <div className="task-log-toolbar"><label>기록일<input type="date" value={workDate} onChange={(event) => setWorkDate(event.target.value)} /></label><label>Owner<select value={owner} onChange={(event) => setOwner(event.target.value)}><option value="">전체 담당자</option>{owners.map((item) => <option key={item}>{item}</option>)}</select></label><label>Agent<select value={agent} onChange={(event) => setAgent(event.target.value)}><option value="">전체 Agent</option>{AGENTS.map((item) => <option key={item}>{item}</option>)}</select></label></div>
    <div className="task-log-scroll" ref={scrollRef} onScroll={handleScroll}><div className="task-log-table-head"><span>시간</span><span>Agent</span><span>Task</span><span>Owner</span><span>상태</span><span>결과</span></div>{items.map((item) => <div className="task-log-row" key={item.log_id}><span>{new Date(item.recorded_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</span><span><b className={`agent-chip agent-${AGENTS.indexOf(item.agent)}`}>{item.agent}</b></span><strong>{item.task_name}</strong><span className="task-log-owner">{item.owner}</span><span><b className="task-log-status">{item.status}</b></span><span className="task-log-result">{item.result_summary}</span></div>)}{loading && <p className="task-log-empty">기록을 불러오는 중...</p>}{!loading && !items.length && <p className="task-log-empty">해당 날짜의 작업 기록이 없습니다.</p>}{!loading && items.length > 0 && !hasMore && <p className="task-log-end">이전 기록이 없습니다.</p>}</div>
  </section>;
}
