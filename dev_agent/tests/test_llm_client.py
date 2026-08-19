import requests

from graph.llm_client import chat_completion


class _FakeResponse:
    def __init__(self, status_code=200, content="결과"):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _fake_post(responses):
    calls = {"count": 0}

    def post(url, json, headers, timeout):
        effect = responses[calls["count"]]
        calls["count"] += 1
        if isinstance(effect, Exception):
            raise effect
        return effect

    return post, calls


def test_chat_completion_returns_content_on_success(monkeypatch):
    post, calls = _fake_post([_FakeResponse(200, "결과")])
    monkeypatch.setattr("graph.llm_client.requests.post", post)

    result = chat_completion([{"role": "user", "content": "안녕"}])

    assert result == "결과"
    assert calls["count"] == 1


def test_chat_completion_retries_on_timeout(monkeypatch):
    monkeypatch.setattr("graph.llm_client.time.sleep", lambda _: None)
    post, calls = _fake_post([requests.exceptions.Timeout(), _FakeResponse(200, "결과")])
    monkeypatch.setattr("graph.llm_client.requests.post", post)

    result = chat_completion([{"role": "user", "content": "안녕"}])

    assert result == "결과"
    assert calls["count"] == 2


def test_chat_completion_retries_on_5xx_and_429(monkeypatch):
    monkeypatch.setattr("graph.llm_client.time.sleep", lambda _: None)
    post, calls = _fake_post([_FakeResponse(503), _FakeResponse(429), _FakeResponse(200, "결과")])
    monkeypatch.setattr("graph.llm_client.requests.post", post)

    result = chat_completion([{"role": "user", "content": "안녕"}])

    assert result == "결과"
    assert calls["count"] == 3


def test_chat_completion_does_not_retry_on_404(monkeypatch):
    monkeypatch.setattr("graph.llm_client.time.sleep", lambda _: None)
    post, calls = _fake_post([_FakeResponse(404), _FakeResponse(200, "결과")])
    monkeypatch.setattr("graph.llm_client.requests.post", post)

    try:
        chat_completion([{"role": "user", "content": "안녕"}])
        assert False, "재시도 불가능한 오류인데 예외가 안 났다"
    except requests.HTTPError:
        pass

    assert calls["count"] == 1


def test_chat_completion_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("graph.llm_client.time.sleep", lambda _: None)
    post, calls = _fake_post(
        [requests.exceptions.Timeout(), requests.exceptions.Timeout(), requests.exceptions.Timeout(), _FakeResponse(200, "결과")]
    )
    monkeypatch.setattr("graph.llm_client.requests.post", post)

    try:
        chat_completion([{"role": "user", "content": "안녕"}])
        assert False, "최대 시도 횟수를 넘겼는데 예외가 안 났다"
    except requests.exceptions.Timeout:
        pass

    assert calls["count"] == 3
