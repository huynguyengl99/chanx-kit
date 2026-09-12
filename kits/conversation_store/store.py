"""An agent conversation, held as an opaque string so one backend serves every agent
framework. The in-memory default is process-local; implement
:class:`ConversationStore` against your database for anything real."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ConversationStore(Protocol):
    """A thread's conversation, opaque to this kit."""

    async def load(self, thread_id: str) -> str | None:
        """The stored conversation, or ``None`` when the thread has none yet."""
        ...

    async def save(self, thread_id: str, conversation: str) -> None: ...

    async def delete(self, thread_id: str) -> None:
        """Forget the thread. Missing threads are not an error."""
        ...


class InMemoryConversationStore(ConversationStore):
    """Process-local and not durable."""

    def __init__(self) -> None:
        self._threads: dict[str, str] = {}

    async def load(self, thread_id: str) -> str | None:
        return self._threads.get(thread_id)

    async def save(self, thread_id: str, conversation: str) -> None:
        self._threads[thread_id] = conversation

    async def delete(self, thread_id: str) -> None:
        self._threads.pop(thread_id, None)

    def reset(self) -> None:
        """Drop every conversation. Useful between tests."""
        self._threads.clear()
