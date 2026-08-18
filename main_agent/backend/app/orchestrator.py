import asyncio

from .contracts import AgentCard, TaskEvent, TaskRecord, TaskStatus
from .task_store import TaskStore


class Orchestrator:
    def __init__(self, client, store: TaskStore | None = None, router=None):
        self.client = client
        self.store = store or TaskStore()
        self.router = router

    def _select(self, request: str, cards: list[AgentCard]) -> list[AgentCard]:
        terms = {
            "dev-agent": ("코드", "PR", "CI", "배포", "리뷰"),
            "game-qna-agent": ("게임", "세계관", "설정", "Q&A", "전우치", "홍길동", "도감", "카탈로그"),
            "video-agent": ("영상", "스토리보드", "렌더"),
            "workmate-agent": ("회의", "보고서", "브리핑", "업무"),
        }
        selected = [card for card in cards if any(term.lower() in request.lower() for term in terms.get(card.name, ())) ]
        return selected or cards[:1]

    async def select(self, request: str, cards: list[AgentCard]) -> list[AgentCard]:
        if self.router is not None:
            routed = await self.router.select(request)
            if routed:
                selected = [card for card in cards if card.name in routed["selected_agents"]]
                if selected:
                    return selected
        return self._select(request, cards)

    async def run(self, request: str, cards: list[AgentCard]) -> TaskRecord:
        selected = self._select(request, cards)
        task = self.store.create(request, [card.name for card in selected])
        self.store.update(task.task_id, status=TaskStatus.RUNNING)
        for card in selected:
            self.store.append_event(task.task_id, TaskEvent(agent=card.name, type="started", message="Agent 호출 시작"))
        outcomes = await asyncio.gather(
            *(self.client.send_message(card.url, {"message": request}) for card in selected),
            return_exceptions=True,
        )
        results = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
        failures = [str(outcome) for outcome in outcomes if isinstance(outcome, Exception)]
        for card, outcome in zip(selected, outcomes):
            self.store.append_event(
                task.task_id,
                TaskEvent(agent=card.name, type="failed" if isinstance(outcome, Exception) else "completed", message=str(outcome)),
            )
        if failures:
            return self.store.update(task.task_id, status=TaskStatus.FAILED, error="; ".join(failures), result={"results": results})
        return self.store.update(task.task_id, status=TaskStatus.SUCCEEDED, result={"results": results})
