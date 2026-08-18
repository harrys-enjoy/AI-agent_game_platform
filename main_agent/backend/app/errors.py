from typing import Any


STATUS_HTTP_CODES = {
    "INVALID_ARGUMENT": 400,
    "UNAUTHENTICATED": 401,
    "NOT_FOUND": 404,
    "UNAVAILABLE": 503,
    "INTERNAL": 502,
}


class A2AError(RuntimeError):
    def __init__(self, code: int, status: str, message: str, request_id: str | None = None):
        self.code = code
        self.status = status
        self.message = message
        self.request_id = request_id
        self.http_status = STATUS_HTTP_CODES.get(status, code if 400 <= code < 600 else 502)
        super().__init__(message)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], fallback_code: int) -> "A2AError":
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code", fallback_code)
        status = error.get("status", "INTERNAL")
        message = error.get("message", "A2A request failed")
        request_id = error.get("requestId") or payload.get("requestId")
        return cls(int(code), str(status), str(message), request_id)

    def to_dict(self) -> dict[str, Any]:
        error = {"code": self.code, "status": self.status, "message": self.message}
        if self.request_id:
            error["requestId"] = self.request_id
        return {"error": error}

    def __str__(self) -> str:
        return f"{self.status}: {self.message}"
