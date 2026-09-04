"""Redis-backed presence roster, shared across workers.

Each scope is a Redis hash of ``connection_id -> member JSON``. Membership is derived
from the hash rather than a counter, so a crashed worker leaves at most stale entries
that expire.
"""

from typing import Any

from redis.asyncio import Redis

from ..presence.messages import PresenceMember
from ..presence.store import PresenceStore


class RedisPresenceStore(PresenceStore):
    """Presence roster shared across workers via Redis. ``ttl`` bounds how long a
    roster survives with no writes; every write refreshes it."""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "chanx-kit:presence",
        ttl: int = 3600,
    ) -> None:
        self._redis = redis
        self._key_prefix = key_prefix
        self._ttl = ttl

    def _key(self, scope: str) -> str:
        return f"{self._key_prefix}:{scope}"

    async def add(self, scope: str, connection_id: str, member: PresenceMember) -> bool:
        key = self._key(scope)
        existing = await self._members(key)
        already_present = any(m.id == member.id for m in existing.values())

        pipe = self._redis.pipeline()
        pipe.hset(key, connection_id, member.model_dump_json())
        pipe.expire(key, self._ttl)
        await pipe.execute()

        return not already_present

    async def discard(self, scope: str, connection_id: str) -> PresenceMember | None:
        key = self._key(scope)
        raw: Any = await self._redis.hget(key, connection_id)
        if raw is None:
            return None

        member = PresenceMember.model_validate_json(raw)
        await self._redis.hdel(key, connection_id)

        remaining = await self._members(key)
        if any(m.id == member.id for m in remaining.values()):
            return None
        return member

    async def members(self, scope: str) -> list[PresenceMember]:
        by_id: dict[str, PresenceMember] = {}
        for member in (await self._members(self._key(scope))).values():
            by_id.setdefault(member.id, member)
        return list(by_id.values())

    async def _members(self, key: str) -> dict[str, PresenceMember]:
        raw: dict[Any, Any] = await self._redis.hgetall(key)
        return {
            _decode(connection_id): PresenceMember.model_validate_json(payload)
            for connection_id, payload in raw.items()
        }


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
