"""EntityCacheService — Redis snapshot for Crystallizer prompt injection."""

import json
import uuid


class EntityCacheService:
    def __init__(self, redis) -> None:
        self.redis = redis

    async def get_snapshot(
        self, workspace_id: uuid.UUID, types: list[str] | None = None, limit: int = 100
    ) -> list[dict]:
        """Get entity snapshot from Redis cache for Crystallizer prompt injection.

        Returns list of dicts: {"name": ..., "entity_type": ..., "aliases": [...]}
        """
        if self.redis is None:
            return []

        key = f"entity_cache:{workspace_id}"
        # Get all members from sorted set (scored by last_seen_at timestamp)
        raw_members = await self.redis.zrevrange(key, 0, limit - 1)
        if not raw_members:
            return []
        # Get entity details from hash
        hash_key = f"entity_cache:{workspace_id}:details"
        pipeline = self.redis.pipeline()
        for member in raw_members:
            pipeline.hget(hash_key, member)
        details = await pipeline.execute()
        entities = []
        for member, detail in zip(raw_members, details):
            if detail:
                entity = json.loads(detail)
                if types is None or entity.get("entity_type") in types:
                    entities.append(entity)
        return entities[:limit]

    async def warm(
        self, workspace_id: uuid.UUID, entities: list[dict], ttl: int = 3600
    ) -> None:
        """Populate cache from DB entities.

        Each entity dict: {name, entity_type, aliases, last_seen_at}
        """
        if self.redis is None:
            return

        key = f"entity_cache:{workspace_id}"
        hash_key = f"entity_cache:{workspace_id}:details"
        pipeline = self.redis.pipeline()
        for entity in entities:
            score = entity.get("last_seen_at", 0)
            if hasattr(score, "timestamp"):
                score = score.timestamp()
            member = entity["name"]
            pipeline.zadd(key, {member: score})
            pipeline.hset(
                hash_key,
                member,
                json.dumps(
                    {
                        "name": entity["name"],
                        "entity_type": entity["entity_type"],
                        "aliases": entity.get("aliases", []),
                    }
                ),
            )
        pipeline.expire(key, ttl)
        pipeline.expire(hash_key, ttl)
        await pipeline.execute()

    async def invalidate(self, workspace_id: uuid.UUID, entity_name: str) -> None:
        """Remove a single entity from cache."""
        if self.redis is None:
            return

        key = f"entity_cache:{workspace_id}"
        hash_key = f"entity_cache:{workspace_id}:details"
        pipeline = self.redis.pipeline()
        pipeline.zrem(key, entity_name)
        pipeline.hdel(hash_key, entity_name)
        await pipeline.execute()

    async def invalidate_batch(self, workspace_id: uuid.UUID, entity_names: list[str]) -> None:
        """Remove multiple entities from cache."""
        if self.redis is None:
            return

        if not entity_names:
            return
        key = f"entity_cache:{workspace_id}"
        hash_key = f"entity_cache:{workspace_id}:details"
        pipeline = self.redis.pipeline()
        pipeline.zrem(key, *entity_names)
        pipeline.hdel(hash_key, *entity_names)
        await pipeline.execute()
