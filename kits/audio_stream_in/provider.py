"""What a provider adapter implements: a stream of audio in, frames out."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class SpeechStartedFrame:
    at_ms: int


@dataclass
class PartialFrame:
    text: str
    start_ms: int
    end_ms: int


@dataclass
class FinalFrame:
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None


@dataclass
class UtteranceEndFrame:
    pass


TranscriberFrame = SpeechStartedFrame | PartialFrame | FinalFrame | UtteranceEndFrame


class ProviderUnavailableError(Exception):
    """The provider cannot be used: no credentials, or it refused the connection."""


class TranscriberStream(Protocol):
    """One provider stream: audio in, frames out until the provider closes."""

    async def send(self, audio: bytes) -> None: ...

    async def keepalive(self) -> None:
        """Called while no audio arrives, so the provider does not time out."""
        ...

    async def finish(self) -> None:
        """Flush what the provider holds and close once its last results are out."""
        ...

    async def close(self) -> None:
        """Close now, abandoning pending results."""
        ...

    def frames(self) -> AsyncIterator[TranscriberFrame]: ...
