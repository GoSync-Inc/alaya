import hashlib
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from alayaos_core.models.api_key import APIKey
from alayaos_core.repositories.api_key import APIKeyRepository


def generate_raw_key() -> tuple[str, str, str]:
    """Generate raw key, prefix, and hash. Returns (raw_key, prefix, key_hash)."""
    raw = secrets.token_urlsafe(32)
    raw_key = f"ak_{raw}"
    prefix = raw_key[:12]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, prefix, key_hash


async def create_api_key(
    session: AsyncSession,
    workspace_id,
    name: str,
    scopes: list[str] | None = None,
    is_bootstrap: bool = False,
    expires_at=None,
) -> tuple[APIKey, str]:
    """Create API key. Returns (api_key_model, raw_key). Raw key shown once only."""
    raw_key, prefix, key_hash = generate_raw_key()
    repo = APIKeyRepository(session)
    api_key = await repo.create(
        workspace_id=workspace_id,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=scopes or ["read", "write"],
        is_bootstrap=is_bootstrap,
        expires_at=expires_at,
    )
    return api_key, raw_key
