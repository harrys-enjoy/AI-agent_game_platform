"""Elice mlapi.run 엔드포인트 호출 — supervisor 라우팅과 workers 생성 요청이 공유하는 단일 클라이언트.

OpenAI 호환 API다. base_url(ELICE_API_URL)에 /v1/chat/completions를 붙이고
model 필드를 명시해야 한다. langchain/openai SDK 없이 requests로 직접 POST한다.
"""
import os
import time

import requests

ELICE_API_URL = os.getenv("ELICE_API_URL", "https://mlapi.run/e9a5f41b-fdda-44f2-9545-ed88c458da53")
ELICE_API_KEY = os.getenv("ELICE_API_KEY", "")
ELICE_MODEL = os.getenv("ELICE_MODEL", "claude-sonnet-5")

_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE_SEC = 1.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    """일시적 오류(타임아웃/연결 오류/429/5xx)만 재시도 대상으로 본다.

    401/403/404 같은 설정 오류는 몇 번을 다시 불러도 똑같이 실패하므로 재시도하지 않는다.
    """
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status in _RETRYABLE_STATUS_CODES
    return False


def chat_completion(messages: list[dict], max_tokens: int = 16000, timeout: int = 30) -> str:
    """OpenAI 호환 messages 배열을 보내고 응답 텍스트(content)를 돌려준다."""
    payload = {"model": ELICE_MODEL, "messages": messages, "max_tokens": max_tokens}
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {ELICE_API_KEY}",
    }
    url = f"{ELICE_API_URL}/v1/chat/completions"

    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            if not _is_retryable(exc) or attempt == _RETRY_MAX_ATTEMPTS - 1:
                raise
            time.sleep(_RETRY_BACKOFF_BASE_SEC * (2**attempt))
