"""Presence roster storage. The in-process default is wrong the moment you run two
workers, so swap in the ``redis-presence-store`` kit or your own
:class:`PresenceStore`."""

from collections import defaultdict
from typing import Protocol, runtime_checkable

from .messages import PresenceMember


@runtime_checkable
class PresenceStore(Protocol):
    """Storage backing the presence roster for each scope."""

    async def add(self, scope: str, connection_id: str, member: PresenceMember) -> bool:
        """Record a connection. Returns ``True`` if the member became newly present,
        so one user with three tabs produces one join event."""
        ...

    async def discard(self, scope: str, connection_id: str) -> PresenceMember | None:
        """Forget a connection. Returns the member if that was their last connection."""
        ...

    async def members(self, scope: str) -> list[PresenceMember]:
        """Everyone currently present in ``scope``."""
        ...


class InMemoryPresenceStore(PresenceStore):
    """Process-local presence store; rosters are incomplete with multiple workers."""

    def __init__(self) -> None:
        self._connections: dict[str, dict[str, PresenceMember]] = defaultdict(dict)

    async def add(self, scope: str, connection_id: str, member: PresenceMember) -> bool:
        connections = self._connections[scope]
        already_present = any(m.id == member.id for m in connections.values())
        connections[connection_id] = member
        return not already_present

    async def discard(self, scope: str, connection_id: str) -> PresenceMember | None:
        connections = self._connections.get(scope)
        if not connections:
            return None
        member = connections.pop(connection_id, None)
        if member is None:
            return None
        if not connections:
            del self._connections[scope]
        elif any(m.id == member.id for m in connections.values()):
            return None
        return member

    async def members(self, scope: str) -> list[PresenceMember]:
        seen: dict[str, PresenceMember] = {}
        for member in self._connections.get(scope, {}).values():
            seen.setdefault(member.id, member)
        return list(seen.values())

    def clear(self) -> None:
        """Drop all state. Useful between tests."""
        self._connections.clear()
