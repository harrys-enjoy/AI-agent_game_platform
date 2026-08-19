from typing import Annotated, Optional, TypedDict


def merge_results(existing: dict, update: dict) -> dict:
    """워커별 결과 dict를 키 단위로 병합하는 리듀서. existing을 변경하지 않는다."""
    merged = dict(existing)
    merged.update(update)
    return merged


class State(TypedDict):
    request: str
    repo: str
    pr_number: Optional[int]
    diff: str
    readme: str
    branches: list[str]
    prs: list[dict]
    ci_logs: list[dict]
    ci_status: str
    pending: list[str]
    planned: bool
    results: Annotated[dict, merge_results]
    next: str
    final_response: str
    history_context: str
