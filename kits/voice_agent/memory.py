"""The conversation a voice agent keeps, since no client sends it."""

from typing import Protocol, runtime_checkable

from ag_ui.core import AssistantMessage, UserMessage

Turn = UserMessage | AssistantMessage


@runtime_checkable
class VoiceMemory(Protocol):
    async def load(self, thread_id: str) -> list[Turn]: ...

    async def save(self, thread_id: str, turns: list[Turn]) -> None: ...


class InMemoryVoiceMemory(VoiceMemory):
    """Process-local, bounded per thread. Implement the protocol to persist it."""

    def __init__(self, max_turns: int = 100) -> None:
        self._max = max_turns
        self._threads: dict[str, list[Turn]] = {}

    async def load(self, thread_id: str) -> list[Turn]:
        return list(self._threads.get(thread_id, ()))

    async def save(self, thread_id: str, turns: list[Turn]) -> None:
        self._threads[thread_id] = list(turns)[-self._max :]

    def reset(self) -> None:
        self._threads.clear()
