"""최근 대화/작업 이력을 보관한다.

LangGraph State는 쿼리마다 리셋되는 설계를 유지하되(supervisor.py의 재계획 로직 참고),
오류 보고나 작업 내역 문서화 수요에 대응하기 위해 최근 HISTORY_MAXLEN턴의 (요청, 실행된
워커, 최종 응답, 오류)만 UI 세션 레벨에서 얕게 기록한다. 그래프 State나 checkpointer는
건드리지 않는다.
"""

from collections import deque
from typing import Optional, TypedDict


HISTORY_MAXLEN = 8


class HistoryEntry(TypedDict):
    request: str
    repo: str
    pr_number: Optional[int]
    executed_nodes: list[str]
    final_response: str
    error: Optional[str]


def new_history() -> "deque[HistoryEntry]":
    return deque(maxlen=HISTORY_MAXLEN)


def record_turn(
    history: "deque[HistoryEntry]",
    request: str,
    repo: str,
    pr_number: Optional[int],
    executed_nodes: list[str],
    final_response: str,
    error: Optional[str] = None,
) -> HistoryEntry:
    """이번 턴을 history에 append한다. 가득 차면 가장 오래된 턴을 자동으로 밀어낸다."""
    entry: HistoryEntry = {
        "request": request,
        "repo": repo,
        "pr_number": pr_number,
        "executed_nodes": [n for n in executed_nodes if n != "supervisor"],
        "final_response": final_response,
        "error": error,
    }
    history.append(entry)
    return entry


def format_recent(history: "deque[HistoryEntry]") -> str:
    """supervisor 플래너 프롬프트에 붙일 최근 대화 요약. 기록이 없으면 빈 문자열."""
    if not history:
        return ""
    lines = ["최근 대화 (오래된 순, 참고용):"]
    for i, turn in enumerate(history, 1):
        status = f"오류: {turn['error']}" if turn["error"] else f"실행: {', '.join(turn['executed_nodes']) or '없음'}"
        lines.append(f"{i}. 요청: {turn['request']} | {status}")
    return "\n".join(lines)
