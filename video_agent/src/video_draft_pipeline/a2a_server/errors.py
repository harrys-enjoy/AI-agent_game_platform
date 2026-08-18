from fastapi.responses import JSONResponse

STATUS_HTTP_CODES = {
    "INVALID_ARGUMENT": 400,
    "UNAUTHENTICATED": 401,
    "PERMISSION_DENIED": 403,
    "NOT_FOUND": 404,
    "UNAVAILABLE": 503,
}


def error_response(status: str, message: str) -> JSONResponse:
    code = STATUS_HTTP_CODES[status]
    return JSONResponse(
        status_code=code,
        content={"error": {"code": code, "status": status, "message": message}},
    )
