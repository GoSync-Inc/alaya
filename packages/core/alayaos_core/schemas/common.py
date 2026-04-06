from pydantic import BaseModel


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: list[ErrorDetail] | None = None


class PaginationInfo(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int


class PaginatedResponse[T](BaseModel):
    items: list[T]
    pagination: PaginationInfo


class HealthCheck(BaseModel):
    name: str
    status: str
    message: str | None = None


class HealthResponse(BaseModel):
    status: str
    checks: list[HealthCheck]
