"""OpenAI realtime transcription behind the transcriber contract."""

import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar

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

# OpenAI realtime takes PCM16 mono at this rate only.
PCM_RATE = 24000


class OpenAITranscriberStream:
    """One realtime transcription session: base64 PCM up, text deltas down."""

    def __init__(self, socket: ClientConnection, sample_rate: int) -> None:
        self._socket = socket
        self._rate = sample_rate
        self._ms = 0.0
        self._partials: dict[str, str] = {}
        self._finishing = False
        self._done = False

    async def send(self, audio: bytes) -> None:
        await self._event(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio).decode("ascii"),
            }
        )
        self._ms += len(audio) / (self._rate * 2) * 1000

    async def keepalive(self) -> None:
        pass  # the session stays open while idle

    async def finish(self) -> None:
        self._finishing = True
        await self._event({"type": "input_audio_buffer.commit"})

    async def close(self) -> None:
        self._finishing = True
        await self._socket.close()

    async def frames(self) -> AsyncIterator[TranscriberFrame]:
        try:
            async for raw in self._socket:
                event: dict[str, Any] = json.loads(raw)
                for frame in self._frames_for(event):
                    yield frame
                if self._done:
                    break
        except ConnectionClosed:
            if not self._finishing:
                raise
        finally:
            await self._socket.close()

    def _frames_for(self, event: dict[str, Any]) -> list[TranscriberFrame]:
        now = round(self._ms)
        item = str(event.get("item_id", ""))
        match event.get("type"):
            case "input_audio_buffer.speech_started":
                at = int(event.get("audio_start_ms", now))
                return [SpeechStartedFrame(at_ms=at)]
            case "conversation.item.input_audio_transcription.delta":
                delta = str(event.get("delta", ""))
                self._partials[item] = self._partials.get(item, "") + delta
                text = self._partials[item].strip()
                return [PartialFrame(text=text, start_ms=0, end_ms=now)] if text else []
            case "conversation.item.input_audio_transcription.completed":
                self._partials.pop(item, None)
                self._done = self._finishing
                text = str(event.get("transcript", "")).strip()
                # Each committed item is one turn.
                final: list[TranscriberFrame] = (
                    [FinalFrame(text=text, start_ms=0, end_ms=now)] if text else []
                )
                return [*final, UtteranceEndFrame()]
            case "error":
                error: dict[str, Any] = event.get("error") or {}
                # Committing an empty buffer at the end is not a failure.
                if self._finishing and "buffer" in str(error.get("code", "")):
                    self._done = True
                    return []
                raise RuntimeError(f"OpenAI: {error.get('message', error)}")
            case _:
                return []

    async def _event(self, event: dict[str, Any]) -> None:
        try:
            await self._socket.send(json.dumps(event))
        except ConnectionClosed:
            pass


class OpenAITranscriberTopic(TranscriberTopic):
    """OpenAI realtime transcription; the key comes from ``OPENAI_API_KEY``."""

    # None reads OPENAI_API_KEY when used, so a .env loaded after import works.
    api_key: ClassVar[str | None] = None
    url: ClassVar[str] = "wss://api.openai.com/v1/realtime?intent=transcription"
    model: ClassVar[str] = "gpt-live-transcribe"
    # {"type": "server_vad"} ends turns on silence (barge-in needs it); it needs
    # gpt-4o-transcribe or -mini, since gpt-live-transcribe refuses turn detection.
    turn_detection: ClassVar[dict[str, Any] | None] = None

    @classmethod
    def key(cls) -> str | None:
        return cls.api_key or os.environ.get("OPENAI_API_KEY")

    def provider_available(self) -> bool:
        return bool(self.key())

    def session_update(self, audio: AudioStart) -> dict[str, Any]:
        transcription: dict[str, Any] = {"model": self.model}
        if audio.language:
            transcription["language"] = audio.language
        return {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": audio.sample_rate},
                        "transcription": transcription,
                        "turn_detection": self.turn_detection,
                    }
                },
            },
        }

    async def open_stream(self, audio: AudioStart) -> OpenAITranscriberStream:
        if not (api_key := self.key()):
            raise ProviderUnavailableError("OPENAI_API_KEY is not set.")
        if audio.sample_rate != PCM_RATE or audio.channels != 1:
            raise ProviderUnavailableError(
                "OpenAI realtime takes PCM16 mono at 24 kHz."
            )
        try:
            socket = await connect(
                self.url,
                additional_headers={"Authorization": f"Bearer {api_key}"},
                max_size=None,
            )
        except InvalidStatus as error:
            status = error.response.status_code
            raise ProviderUnavailableError(
                f"OpenAI refused the connection ({status})."
            ) from error
        except OSError as error:
            raise ProviderUnavailableError(f"OpenAI is unreachable: {error}") from error
        await socket.send(json.dumps(self.session_update(audio)))
        return OpenAITranscriberStream(socket, audio.sample_rate)
