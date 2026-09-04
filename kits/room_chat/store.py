"""Chat history persistence. Implement :class:`MessageStore` against your database;
the in-memory default is for demos and tests."""

from collections import defaultdict, deque
from typing import Protocol, runtime_checkable

from .messages import ChatEntry


@runtime_checkable
class MessageStore(Protocol):
    """Persistence for room history."""

    async def append(self, entry: ChatEntry) -> None:
        """Persist a message."""
        ...

    async def backlog(self, room: str, limit: int) -> list[ChatEntry]:
        """Return up to ``limit`` recent messages, oldest first."""
        ...


class InMemoryMessageStore(MessageStore):
    """Process-local, bounded history. Not durable; not shared across workers."""

    def __init__(self, max_per_room: int = 200) -> None:
        self._max_per_room = max_per_room
        self._rooms: dict[str, deque[ChatEntry]] = defaultdict(
            lambda: deque(maxlen=max_per_room)
        )

    async def append(self, entry: ChatEntry) -> None:
        self._rooms[entry.room].append(entry)

    async def backlog(self, room: str, limit: int) -> list[ChatEntry]:
        entries = self._rooms.get(room)
        if not entries:
            return []
        return list(entries)[-limit:]

    def clear(self) -> None:
        """Drop all history. Useful between tests."""
        self._rooms.clear()
