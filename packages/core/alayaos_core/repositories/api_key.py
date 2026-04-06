import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.base import BaseRepository


class APIKeyRepository(BaseRepository):
    async def create(
        self,
        workspace_id: uuid.UUID,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: list[str] | None = None,
        is_bootstrap: bool = False,
        expires_at: datetime | None = None,
    ) -> APIKey:
        api_key = APIKey(
            workspace_id=workspace_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes or ["read", "write"],
            is_bootstrap=is_bootstrap,
            expires_at=expires_at,
        )
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def get_by_prefix(self, key_prefix: str) -> APIKey | None:
        stmt = select(APIKey).where(APIKey.key_prefix == key_prefix)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        workspace_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[APIKey], str | None, bool]:
        stmt = select(APIKey).where(APIKey.workspace_id == workspace_id)
        stmt = self.apply_cursor_pagination(stmt, cursor, limit, APIKey.created_at, APIKey.id)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        actual_limit = min(max(limit, 1), 200)
        has_more = len(items) > actual_limit
        if has_more:
            items = items[:actual_limit]
        next_cursor = self.encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return items, next_cursor, has_more

    async def revoke(self, key_prefix: str) -> APIKey | None:
        api_key = await self.get_by_prefix(key_prefix)
        if api_key is None:
            return None

        api_key.revoked_at = datetime.now(UTC)
        await self.session.flush()
        return api_key
