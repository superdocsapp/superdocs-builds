from fastapi.responses import JSONResponse


def failure(status_code: int, error: str, issues: list[dict] | None = None, message: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"success": False, "message": message, "error": error, "issues": issues or []})
