"""Deepgram live speech-to-text behind the transcriber contract."""

import json
import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ..audio_stream_in import (
    AudioStart,
    FinalFrame,
    PartialFrame,
    ProviderUnavailableError,
    SpeechStartedFrame,
    TranscriberFrame,
    TranscriberTopic,
    UtteranceEndFrame,
)


def frames_from(message: dict[str, Any]) -> list[TranscriberFrame]:
    """Map one Deepgram server message to transcriber frames."""
    match message:
        case {"type": "SpeechStarted"}:
            at = float(message.get("timestamp", 0))
            return [SpeechStartedFrame(at_ms=round(at * 1000))]
        case {"type": "UtteranceEnd"}:
            return [UtteranceEndFrame()]
        case {"type": "Results"}:
            return _results(message)
        case _:
            return []


def _results(message: dict[str, Any]) -> list[TranscriberFrame]:
    channel: dict[str, Any] = message.get("channel") or {}
    alternatives: list[dict[str, Any]] = channel.get("alternatives") or [{}]
    best = alternatives[0]
    text = str(best.get("transcript", "")).strip()
    start_ms = round(float(message.get("start", 0)) * 1000)
    end_ms = start_ms + round(float(message.get("duration", 0)) * 1000)
    frames: list[TranscriberFrame] = []
    match (text, message.get("is_final")):
        case ("", _):
            pass  # Deepgram sends empty results for silence
        case (_, True):
            frames.append(
                FinalFrame(
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    confidence=best.get("confidence"),
                )
            )
        case _:
            frames.append(PartialFrame(text=text, start_ms=start_ms, end_ms=end_ms))
    # Endpointing: the speaker paused.
    if message.get("is_final") and message.get("speech_final"):
        frames.append(UtteranceEndFrame())
    return frames


class DeepgramStream:
    """One Deepgram live connection: binary audio up, JSON results down."""

    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket
        self._closing = False

    @classmethod
    async def open(cls, url: str, api_key: str) -> "DeepgramStream":
        try:
            socket = await connect(
                url,
                additional_headers={"Authorization": f"Token {api_key}"},
                max_size=None,
            )
        except InvalidStatus as error:
            status = error.response.status_code
            raise ProviderUnavailableError(
                f"Deepgram refused the connection ({status})."
            ) from error
        except OSError as error:
            raise ProviderUnavailableError(
                f"Deepgram is unreachable: {error}"
            ) from error
        return cls(socket)

    async def send(self, audio: bytes) -> None:
        await self._socket.send(audio)

    async def keepalive(self) -> None:
        await self._control("KeepAlive")

    async def finish(self) -> None:
        # Finalize flushes; CloseStream sends the rest and closes, which ends frames().
        await self._control("Finalize")
        await self._control("CloseStream")

    async def close(self) -> None:
        self._closing = True
        await self._control("CloseStream")
        await self._socket.close()

    async def frames(self) -> AsyncIterator[TranscriberFrame]:
        try:
            async for raw in self._socket:
                if isinstance(raw, bytes):
                    continue
                for frame in frames_from(json.loads(raw)):
                    yield frame
        except ConnectionClosed:
            if not self._closing:
                raise

    async def _control(self, kind: str) -> None:
        try:
            await self._socket.send(json.dumps({"type": kind}))
        except ConnectionClosed:
            pass


class DeepgramTranscriberTopic(TranscriberTopic):
    """Deepgram live speech-to-text; the key comes from ``DEEPGRAM_API_KEY``."""

    # None reads DEEPGRAM_API_KEY when used, so a .env loaded after import works.
    api_key: ClassVar[str | None] = None
    url: ClassVar[str] = "wss://api.deepgram.com/v1/listen"
    model: ClassVar[str] = "nova-3"
    options: ClassVar[dict[str, str]] = {}
    utterance_end_ms: ClassVar[int] = 1000
    endpointing_ms: ClassVar[int] = 300

    @classmethod
    def key(cls) -> str | None:
        return cls.api_key or os.environ.get("DEEPGRAM_API_KEY")

    def provider_available(self) -> bool:
        return bool(self.key())

    def listen_url(self, audio: AudioStart) -> str:
        query = {
            "model": self.model,
            "encoding": "linear16",
            "sample_rate": str(audio.sample_rate),
            "channels": str(audio.channels),
            "interim_results": "true",
            "vad_events": "true",
            "utterance_end_ms": str(self.utterance_end_ms),
            "endpointing": str(self.endpointing_ms),
            **({"language": audio.language} if audio.language else {}),
            **self.options,
        }
        return f"{self.url}?{urlencode(query)}"

    async def open_stream(self, audio: AudioStart) -> DeepgramStream:
        if not (api_key := self.key()):
            raise ProviderUnavailableError("DEEPGRAM_API_KEY is not set.")
        return await DeepgramStream.open(self.listen_url(audio), api_key)
