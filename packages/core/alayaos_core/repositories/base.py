import base64
import binascii
import json
import uuid
from datetime import datetime

from sqlalchemy import Select, desc
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def encode_cursor(created_at: datetime, id: uuid.UUID) -> str:  # noqa: A002
        payload = {"created_at": created_at.isoformat(), "id": str(id)}
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    @staticmethod
    def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor))
            return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
        except (json.JSONDecodeError, KeyError, ValueError, binascii.Error) as e:
            raise ValueError("Invalid cursor") from e

    @staticmethod
    def apply_cursor_pagination(stmt: Select, cursor: str | None, limit: int, created_at_col, id_col) -> Select:
        limit = min(max(limit, 1), 200)  # clamp
        stmt = stmt.order_by(desc(created_at_col), desc(id_col))
        if cursor:
            cursor_created_at, cursor_id = BaseRepository.decode_cursor(cursor)
            stmt = stmt.where(
                (created_at_col < cursor_created_at) | ((created_at_col == cursor_created_at) & (id_col < cursor_id))
            )
        return stmt.limit(limit + 1)  # fetch one extra to detect has_more
