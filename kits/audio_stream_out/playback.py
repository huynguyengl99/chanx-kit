"""What was said, and how much of it was heard."""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Utterance:
    text: str
    duration_ms: int = 0
    played_ms: int = 0
    finished: bool = False


def heard_text(text: str, duration_ms: int, played_ms: int) -> str:
    """The part of ``text`` heard after ``played_ms``, cut at a word."""
    if duration_ms <= 0:
        return ""
    if played_ms >= duration_ms:
        return text
    cut = int(len(text) * played_ms / duration_ms)
    head = text[:cut]
    if cut < len(text) and not text[cut].isspace() and " " in head:
        head = head[: head.rindex(" ")]
    return head.rstrip()


@runtime_checkable
class PlaybackStore(Protocol):
    async def spoken(self, session: str, utterance_id: str, text: str) -> None: ...

    async def finished(
        self, session: str, utterance_id: str, duration_ms: int
    ) -> None: ...

    async def mark(self, session: str, utterance_id: str, played_ms: int) -> None: ...

    async def get(self, session: str, utterance_id: str) -> Utterance | None: ...


class InMemoryPlaybackStore(PlaybackStore):
    """Process-local; keeps the last ``keep`` utterances per session."""

    def __init__(self, keep: int = 50) -> None:
        self._keep = keep
        self._sessions: dict[str, OrderedDict[str, Utterance]] = {}

    def _session(self, session: str) -> OrderedDict[str, Utterance]:
        return self._sessions.setdefault(session, OrderedDict())

    async def spoken(self, session: str, utterance_id: str, text: str) -> None:
        utterances = self._session(session)
        utterances[utterance_id] = Utterance(text=text)
        while len(utterances) > self._keep:
            utterances.popitem(last=False)

    async def finished(self, session: str, utterance_id: str, duration_ms: int) -> None:
        utterance = self._session(session).get(utterance_id)
        if utterance is not None:
            utterance.duration_ms = duration_ms
            utterance.finished = True

    async def mark(self, session: str, utterance_id: str, played_ms: int) -> None:
        utterance = self._session(session).get(utterance_id)
        if utterance is not None:
            utterance.played_ms = max(utterance.played_ms, played_ms)

    async def get(self, session: str, utterance_id: str) -> Utterance | None:
        return self._session(session).get(utterance_id)

    def reset(self) -> None:
        self._sessions.clear()
