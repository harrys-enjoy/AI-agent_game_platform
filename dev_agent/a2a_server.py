"""팀 A2A 규약(docs/a2a-integration-requirements.md)으로 들어오는 요청을 그래프에 연결한다.

그래프 실행은 가벼운 요청도 20~30초, deploy_trigger가 끼면 수 분까지 걸려 규약의 15초
동기 예산을 항상 넘긴다. 그래서 POST /a2a/message:send는 Task를 만들고 그래프는
백그라운드에서 돌린 뒤 TASK_STATE_WORKING을 즉시 반환하고, 클라이언트는
GET /a2a/tasks/{id}로 폴링해서 완료 여부를 확인한다.

메인 에이전트가 보내는 건 자연어 요청뿐이라, 어떤 레포를 볼지는 metadata.workspace_id를
WORKSPACE_REPO_MAP(env)으로 조회해서 정한다 — 이게 workspace가 건드릴 수 있는 레포의
접근 제어 경계다. 요청 텍스트에 github.com URL이 있으면 참고로 파싱하지만, deploy_trigger가
그 레포를 clone/build/run까지 하므로 워크스페이스에 매핑된 레포와 다르면 거절한다(400).
텍스트 파싱 결과로 접근 제어를 대체하지 않는다.

main_agent(오케스트레이터)는 workspace_id 개념이 없어 metadata.request_id/user_id/
workspace_id를 아예 안 보낸다(실측) — 그래서 이 셋은 전부 optional이고, workspace_id가
없으면 DEFAULT_WORKSPACE_ID(env)로 대체한다. 이것도 결국 WORKSPACE_REPO_MAP의 항목
하나를 가리키므로 접근 제어 경계 자체는 유지된다 — "지정 안 하면 이 레포 하나"로 좁아질
뿐, REPO_ACCESS_CONTROL_DISABLED처럼 아무 레포나 허용하는 것과는 다르다.

Task 저장소는 프로세스 메모리(dict)에만 있다 — 재시작하면 진행 중이던 Task는 사라진다.
소규모 단일 프로세스 배포라 지금은 이걸로 충분하다.

대화 이력(graph/history.py)은 여기서 쓰지 않는다. 프로세스 전역 이력은 서로 다른
user_id/workspace_id의 요청을 한 플래너 프롬프트에 섞어버린다. 이력이 필요해지면
workspace_id/contextId 단위로 분리해서 보관해야 한다.

백그라운드 실행은 FastAPI의 BackgroundTasks(anyio 스레드풀) 대신 threading.Thread(daemon=True)를
직접 쓴다. graph 실행은 subprocess/네트워크 호출투성이라 진짜로 중단이 안 되는데, anyio
스레드풀에 태우면 그 스레드가 uvicorn의 async cancel scope에 묶여서 Ctrl+C 종료 시
"cancel scope in a different task" 에러가 나고 프로세스가 포트를 문 채 안 죽는다. 데몬
스레드는 그 구조와 무관해서, Ctrl+C 시 메인 프로세스가 바로 종료되고(진행 중이던 Task는
그냥 버려짐) 포트도 정상적으로 풀린다.
"""

import os
import re
import threading
import uuid

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

load_dotenv()

from graph.build import build_graph

app = FastAPI()
_bearer_scheme = HTTPBearer(auto_error=False)

_tasks: dict[str, dict] = {}
_message_task_map: dict[tuple[str, str], str] = {}  # (messageId, request_text) -> task_id
_tasks_lock = threading.Lock()

TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}

# 이 에이전트가 스스로를 광고하는 주소. docker-compose 안에서는 서비스명(dev-agent)이
# DNS로 풀리지만, 로컬에서 uvicorn을 직접 띄워 main_agent와 연결할 때는 그 이름이
# 존재하지 않아 getaddrinfo가 실패한다(실측). game-qa-agent의 AGENT_PUBLIC_URL,
# workmate-agent의 APP_BASE_URL과 같은 패턴 — 기본값은 기존 docker-compose 값 그대로 둔다.
DEV_AGENT_PUBLIC_URL = os.getenv("DEV_AGENT_PUBLIC_URL", "http://dev-agent:8003")

AGENT_CARD = {
    # main_agent는 AgentCard.name을 표시용이 아니라 내부 키로 쓴다(레지스트리 등록명과
    # 대조해 헤더/설정을 찾음, main_agent/backend/app/registry.py의 headers()) — 사람이
    # 읽는 이름을 넣으면 실측 시 KeyError가 난다. 그래서 다른 카드들(mock-agents, main.py의
    # 정적 cards 목록)과 똑같이 "dev-agent"를 쓴다. 사람이 읽을 설명은 description에 있다.
    "name": "dev-agent",
    "description": "GitHub PR 리뷰, 브랜치/PR 현황 요약, CI 재실행, 로컬 Docker 배포를 자연어 요청으로 처리하는 개발 보조 에이전트.",
    "version": "1.0.0",
    "provider": {"organization": "kosa"},
    # main_agent(오케스트레이터)의 AgentCard 모델은 최상위 "url"을 필수로 요구한다 — 없으면
    # 카드 파싱이 조용히 실패하고 main_agent가 이 에이전트를 "사용 불가"로 처리한 뒤 로컬
    # 에코 클라이언트로 넘어간다(실측: main_agent/backend/app/registry.py의 refresh()가
    # ValidationError를 삼킴). supportedInterfaces[0].url도 "/message:send"까지 포함해야
    # main_agent의 A2AClient가 HTTP+JSON 분기를 타고, 아니면 JSON-RPC로 POST /a2a를
    # 호출해서 404가 난다(실측) — 팀 문서(a2a-integration-requirements.md)는 base URL만
    # 적으라 하지만, main_agent의 실제 구현은 그렇게 동작하지 않는다.
    "url": f"{DEV_AGENT_PUBLIC_URL}/a2a/message:send",
    "supportedInterfaces": [
        {
            "url": f"{DEV_AGENT_PUBLIC_URL}/a2a/message:send",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        }
    ],
    "skills": [
        {
            "id": "code_assistance",
            "name": "코드 리뷰 및 개발 보조",
            "description": "PR diff 리뷰, 엔드포인트 변경 감지, 브랜치/CI 현황 요약, CI 재실행, 로컬 배포",
            "tags": ["code-review", "ci", "deploy"],
        }
    ],
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["application/json", "text/markdown"],
    "authentication": {"schemes": ["bearer"]},
    "capabilities": {"streaming": False, "pushNotifications": False},
}


def _parse_workspace_repos(raw: str) -> dict[str, str]:
    """WORKSPACE_REPO_MAP="team-a=owner/repo-a,team-b=owner/repo-b" 형식을 파싱한다."""
    mapping = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        workspace_id, repo = entry.split("=", 1)
        mapping[workspace_id.strip()] = repo.strip()
    return mapping


WORKSPACE_REPOS = _parse_workspace_repos(os.getenv("WORKSPACE_REPO_MAP", ""))


def _resolve_workspace_id(metadata_workspace_id: str | None) -> str | None:
    """metadata.workspace_id가 없으면 DEFAULT_WORKSPACE_ID로 대체한다.

    main_agent는 workspace_id 개념 자체가 없어 아예 안 보낸다(실측) — 그래도 접근
    제어 경계를 없애지는 않는다: DEFAULT_WORKSPACE_ID도 결국 WORKSPACE_REPO_MAP의
    항목 하나를 가리켜야 하므로, "지정 안 하면 이 레포 하나로 취급" 정도로 범위가
    좁다(REPO_ACCESS_CONTROL_DISABLED처럼 요청 텍스트의 아무 레포나 허용하는 것과는 다름).
    둘 다 없으면 여전히 400으로 거절된다.
    """
    return metadata_workspace_id or os.getenv("DEFAULT_WORKSPACE_ID")


def _repo_access_control_disabled() -> bool:
    """테스트 편의를 위한 임시 스위치 — 켜지면 workspace_id -> 레포 접근 제어를 완전히
    건너뛰고 요청 텍스트에 언급된 아무 github.com 레포나 그대로 쓴다. deploy_trigger가
    그 레포를 clone/build/run까지 하므로, 이 스위치를 켠 채로 신뢰 안 되는 요청을 받으면
    임의 코드 실행으로 이어진다. 테스트가 끝나면 이 환경변수를 지울 것.

    모듈 로드 시점이 아니라 요청 시점에 읽는다 — 상수로 굳히면 개발자의 환경변수 파일
    값이 테스트 스위트까지 따라 들어와 접근 제어 테스트가 조용히 무력화된다(실제로 겪음).
    """
    return os.getenv("REPO_ACCESS_CONTROL_DISABLED", "false").lower() == "true"


class A2APart(BaseModel):
    text: str
    mediaType: str = "text/plain"


class A2AMessage(BaseModel):
    messageId: str
    role: str
    parts: list[A2APart]


class A2AConfiguration(BaseModel):
    acceptedOutputModes: list[str] = []


class A2AMetadata(BaseModel):
    # 팀 문서(a2a-integration-requirements.md)는 이 셋을 필수로 규정하지만, 실제
    # main_agent(오케스트레이터)는 request_id/user_id/workspace_id를 하나도 안 보낸다
    # (실측, main_agent/backend/app/a2a_client.py). main_agent 기준으로 통신 포맷을
    # 맞추기 위해 전부 optional로 둔다 — request_id/user_id는 어차피 코드에서 안 쓴다.
    # workspace_id만 접근 제어에 실제로 쓰이므로, 없을 때는 DEFAULT_WORKSPACE_ID로
    # 대체한다(아래 _resolve_workspace_id).
    request_id: str | None = None
    user_id: str | None = None
    workspace_id: str | None = None


class A2ASendMessageRequest(BaseModel):
    message: A2AMessage
    configuration: A2AConfiguration = A2AConfiguration()
    metadata: A2AMetadata


def _verify_token(token: str | None) -> None:
    expected = os.getenv("DEV_SERVICE_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="DEV_SERVICE_TOKEN이 설정되지 않았습니다.")
    if token != expected:
        raise HTTPException(status_code=401, detail="인증 토큰이 올바르지 않습니다.")


def _resolve_repo(workspace_id: str) -> str | None:
    return WORKSPACE_REPOS.get(workspace_id)


def _extract_request_text(message: A2AMessage) -> str:
    return "\n".join(part.text for part in message.parts if part.text)


# 레포명 뒤를 "/", "?", "#", 공백, 문자열 끝으로만 끝난다고 보면(원래 구현), 한국어
# 조사가 URL에 공백 없이 바로 붙는 흔한 표현("...whoami의 master 브랜치 배포해봐")에서
# "의" 앞에서 매치 자체가 실패해서 레포를 통째로 못 읽었다 — REPO_ACCESS_CONTROL_DISABLED가
# 켜져 있으면 이때 조용히 워크스페이스 기본 레포로 폴백돼서, 완전히 다른 레포가 배포되는
# 사고로 이어졌다(실제로 겪음). 레포명 문자 집합에 없는 아무 문자(비-ASCII 포함)에서나
# 끝나면 되도록 lookahead로 바꿨다 — _find_mentioned_branch의 _BOUNDARY와 같은 종류의 수정.
_GITHUB_REPO_URL_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?=[^A-Za-z0-9_.-]|$)")


def _parse_repo_from_text(text: str) -> str | None:
    """자연어 요청에 github.com URL이 있으면 owner/repo를 뽑아낸다. 없으면 None.

    ponytail: github.com URL만 인식한다. 'owner/repo' 축약형은 파일 경로 등과 구분이
    안 돼서 오탐이 잦다 — 필요해지면 그때 좁은 문맥(예: "레포:" 접두어)을 추가한다.
    """
    match = _GITHUB_REPO_URL_RE.search(text)
    if not match:
        return None
    owner, repo = match.groups()
    return f"{owner}/{repo}"


def _run_graph(initial_state: dict) -> str:
    graph = build_graph()
    final_state = None
    for step in graph.stream(initial_state, stream_mode="updates"):
        for _node_name, node_output in step.items():
            final_state = node_output
    return (final_state or {}).get("final_response", "")


def _execute_task(task_id: str, initial_state: dict) -> None:
    """백그라운드에서 그래프를 돌리고 Task 상태를 갱신한다.

    ponytail: 그래프 실행을 중간에 끊는 기능은 없다 — cancel은 상태만 바꿔두고,
    실행이 끝났을 때 이미 터미널 상태(취소 등)면 결과를 버린다. 실제 중단이
    필요해지면 각 노드(특히 deploy_trigger의 subprocess)에 취소 신호를 전달하는
    별도 작업이 필요하다.
    """
    try:
        final_response = _run_graph(initial_state)
    except Exception as exc:
        with _tasks_lock:
            task = _tasks.get(task_id)
            if task and task["status"]["state"] not in TERMINAL_STATES:
                task["status"] = {"state": "TASK_STATE_FAILED"}
                task["error"] = str(exc)
        return

    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None or task["status"]["state"] in TERMINAL_STATES:
            return
        task["status"] = {"state": "TASK_STATE_COMPLETED"}
        task["artifacts"] = [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "Agent 처리 결과",
                "parts": [
                    {"text": final_response, "mediaType": "text/markdown"},
                    {"data": {"schema_version": "1.0", "result": {}}, "mediaType": "application/json"},
                ],
            }
        ]


@app.get("/.well-known/agent-card.json")
def agent_card():
    return AGENT_CARD


@app.post("/a2a/message:send")
def send_message(
    payload: A2ASendMessageRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    _verify_token(credentials.credentials if credentials else None)

    request_text = _extract_request_text(payload.message)

    # main_agent는 messageId를 매 요청 "main-agent" 고정값으로 보낸다(실측) — 원래
    # 의도(동일 메시지 재전송 시 같은 Task 반환)와 달리 서로 다른 요청까지 뭉개버린다.
    # (messageId, 요청 텍스트) 조합으로 키를 잡으면 진짜 재전송은 여전히 dedupe하면서
    # messageId만 재사용하는 새 요청은 정상적으로 새 Task를 만든다.
    dedupe_key = (payload.message.messageId, request_text)
    with _tasks_lock:
        existing_task_id = _message_task_map.get(dedupe_key)
        if existing_task_id:
            return {"task": _tasks[existing_task_id]}

    workspace_id = _resolve_workspace_id(payload.metadata.workspace_id)
    repo = _resolve_repo(workspace_id) if workspace_id else None
    mentioned_repo = _parse_repo_from_text(request_text)

    if _repo_access_control_disabled():
        repo = mentioned_repo or repo
        if repo is None:
            raise HTTPException(
                status_code=400,
                detail="레포를 결정할 수 없습니다 — 요청 텍스트에 github.com URL을 포함하거나 workspace_id를 매핑하세요.",
            )
    else:
        if repo is None:
            raise HTTPException(
                status_code=400,
                detail=f"workspace_id '{workspace_id}'에 매핑된 레포가 없습니다.",
            )
        if mentioned_repo is not None and mentioned_repo != repo:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"요청에 언급된 레포 '{mentioned_repo}'는 workspace_id "
                    f"'{workspace_id}'에 허용된 레포('{repo}')와 다릅니다."
                ),
            )

    initial_state = {
        "request": request_text,
        "repo": repo,
        "pr_number": None,
        "diff": "",
        "readme": "",
        "branches": [],
        "prs": [],
        "ci_logs": [],
        "ci_status": "",
        "pending": [],
        "planned": False,
        "results": {},
        "next": "",
        "final_response": "",
        # A2A는 요청마다 독립이다 — 대화 이력을 안 넘긴다. 프로세스 전역 이력을 쓰면
        # 서로 다른 user_id/workspace_id의 요청이 같은 플래너 프롬프트에 섞인다.
        "history_context": "",
    }

    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "contextId": str(uuid.uuid4()),
        "status": {"state": "TASK_STATE_WORKING"},
        "artifacts": [],
    }
    with _tasks_lock:
        _tasks[task_id] = task
        _message_task_map[dedupe_key] = task_id

    threading.Thread(target=_execute_task, args=(task_id, initial_state), daemon=True).start()

    return {"task": task}


@app.get("/a2a/tasks/{task_id}")
def get_task(
    task_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    _verify_token(credentials.credentials if credentials else None)
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task를 찾을 수 없습니다.")
    return {"task": task}


@app.post("/a2a/tasks/{task_id}:cancel")
def cancel_task(
    task_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    _verify_token(credentials.credentials if credentials else None)
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task를 찾을 수 없습니다.")
        if task["status"]["state"] not in TERMINAL_STATES:
            task["status"] = {"state": "TASK_STATE_CANCELED"}
    return {"task": task}
