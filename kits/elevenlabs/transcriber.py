"""ElevenLabs realtime speech-to-text (Scribe) behind the transcriber contract."""

import base64
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

PCM_RATES = (8000, 16000, 22050, 24000, 44100, 48000)
ERRORS = {
    "error",
    "auth_error",
    "quota_exceeded",
    "rate_limited",
    "resource_exhausted",
    "session_time_limit_exceeded",
    "chunk_size_exceeded",
    "input_error",
}


class ElevenLabsTranscriberStream:
    """One Scribe realtime session: base64 PCM up, partial and committed text down."""

    def __init__(self, socket: ClientConnection, sample_rate: int) -> None:
        self._socket = socket
        self._rate = sample_rate
        self._ms = 0.0
        self._segment_start = 0
        self._finishing = False
        # Scribe has no speech-started event; an utterance's first partial stands in.
        self._in_utterance = False
        self._done = False

    async def send(self, audio: bytes) -> None:
        await self._chunk(audio, commit=False)
        self._ms += len(audio) / (self._rate * 2) * 1000

    async def keepalive(self) -> None:
        # Scribe has no keepalive message; an empty chunk keeps the session busy.
        await self._chunk(b"", commit=False)

    async def finish(self) -> None:
        self._finishing = True
        await self._chunk(b"", commit=True)

    async def close(self) -> None:
        self._finishing = True
        await self._socket.close()

    async def frames(self) -> AsyncIterator[TranscriberFrame]:
        try:
            async for raw in self._socket:
                for frame in self._frames_for(json.loads(raw)):
                    yield frame
                if self._done:
                    break
        except ConnectionClosed:
            if not self._finishing:
                raise
        finally:
            await self._socket.close()

    def _frames_for(self, message: dict[str, Any]) -> list[TranscriberFrame]:
        text = str(message.get("text", "")).strip()
        now = round(self._ms)
        match message.get("message_type"):
            case kind if kind in ERRORS:
                raise RuntimeError(f"ElevenLabs {kind}: {message.get('error', '')}")
            case "partial_transcript" if text:
                frames: list[TranscriberFrame] = []
                if not self._in_utterance:
                    self._in_utterance = True
                    frames.append(SpeechStartedFrame(at_ms=self._segment_start))
                frames.append(
                    PartialFrame(text=text, start_ms=self._segment_start, end_ms=now)
                )
                return frames
            case "committed_transcript":
                final: list[TranscriberFrame] = (
                    [FinalFrame(text=text, start_ms=self._segment_start, end_ms=now)]
                    if text
                    else []
                )
                # Scribe commits when voice activity stops.
                self._in_utterance = False
                self._segment_start = now
                self._done = self._finishing
                return [*final, UtteranceEndFrame()]
            case _:
                return []

    async def _chunk(self, audio: bytes, *, commit: bool) -> None:
        try:
            await self._socket.send(
                json.dumps(
                    {
                        "message_type": "input_audio_chunk",
                        "audio_base_64": base64.b64encode(audio).decode("ascii"),
                        "commit": commit,
                        "sample_rate": self._rate,
                    }
                )
            )
        except ConnectionClosed:
            pass


class ElevenLabsTranscriberTopic(TranscriberTopic):
    """ElevenLabs Scribe realtime speech-to-text; the key comes from ``ELEVENLABS_API_KEY``."""

    # None reads ELEVENLABS_API_KEY when used, so a .env loaded after import works.
    api_key: ClassVar[str | None] = None
    url: ClassVar[str] = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
    model_id: ClassVar[str] = "scribe_v2_realtime"
    options: ClassVar[dict[str, str]] = {}

    @classmethod
    def key(cls) -> str | None:
        return cls.api_key or os.environ.get("ELEVENLABS_API_KEY")

    def provider_available(self) -> bool:
        return bool(self.key())

    def realtime_url(self, audio: AudioStart) -> str:
        if audio.sample_rate not in PCM_RATES or audio.channels != 1:
            raise ProviderUnavailableError(
                f"ElevenLabs takes mono PCM at {', '.join(map(str, PCM_RATES))} Hz."
            )
        query = {
            "model_id": self.model_id,
            "audio_format": f"pcm_{audio.sample_rate}",
            "commit_strategy": "vad",
            **({"language_code": audio.language} if audio.language else {}),
            **self.options,
        }
        return f"{self.url}?{urlencode(query)}"

    async def open_stream(self, audio: AudioStart) -> ElevenLabsTranscriberStream:
        if not (api_key := self.key()):
            raise ProviderUnavailableError("ELEVENLABS_API_KEY is not set.")
        try:
            socket = await connect(
                self.realtime_url(audio),
                additional_headers={"xi-api-key": api_key},
                max_size=None,
            )
        except InvalidStatus as error:
            status = error.response.status_code
            raise ProviderUnavailableError(
                f"ElevenLabs refused the connection ({status})."
            ) from error
        except OSError as error:
            raise ProviderUnavailableError(
                f"ElevenLabs is unreachable: {error}"
            ) from error
        return ElevenLabsTranscriberStream(socket, audio.sample_rate)
