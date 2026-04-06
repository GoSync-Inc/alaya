from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    hint: str | None = None
    docs: str | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class PaginationInfo(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False
    count: int = 0


class PaginatedResponse[T](BaseModel):
    data: list[T]
    pagination: PaginationInfo


class HealthResponse(BaseModel):
    status: str  # "ok" or "degraded"
    checks: dict[str, str] = {}  # {"database": "ok", "migrations": "ok", ...}
    first_run: bool = False
