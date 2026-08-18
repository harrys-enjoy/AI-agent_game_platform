import os

from fastapi import Header


class A2AAuthError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def require_a2a_auth(
    authorization: str | None = Header(default=None),
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
) -> None:
    expected_token = os.environ.get("VIDEO_SERVICE_TOKEN")
    if not expected_token or authorization != f"Bearer {expected_token}":
        raise A2AAuthError("Invalid or missing Authorization Bearer token")
    if a2a_version != "1.0":
        raise A2AAuthError("Missing or unsupported A2A-Version header")
