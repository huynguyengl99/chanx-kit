"""What was sent on a stream so far, kept so a connection joining part-way is replayed."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ReplayStore(Protocol):
    """One buffered stream per key; sequence numbers restart when it is cleared."""

    async def append(self, key: str, message: dict[str, Any]) -> int:
        """Buffer a JSON-ready message and return its sequence number, from 1."""
        ...

    async def replay(self, key: str) -> list[tuple[int, dict[str, Any]]]: ...

    async def clear(self, key: str) -> None: ...


class InMemoryReplayStore(ReplayStore):
    """Process-local and bounded. Implement the protocol against Redis to share it."""

    def __init__(self, max_messages: int = 3000) -> None:
        self._max = max_messages
        self._streams: dict[str, list[tuple[int, dict[str, Any]]]] = {}

    async def append(self, key: str, message: dict[str, Any]) -> int:
        buffered = self._streams.setdefault(key, [])
        seq = buffered[-1][0] + 1 if buffered else 1
        # Dropping the oldest costs a late joiner the start, which it sees as a gap.
        if len(buffered) >= self._max:
            del buffered[0]
        buffered.append((seq, message))
        return seq

    async def replay(self, key: str) -> list[tuple[int, dict[str, Any]]]:
        return list(self._streams.get(key, ()))

    async def clear(self, key: str) -> None:
        self._streams.pop(key, None)

    def reset(self) -> None:
        self._streams.clear()
