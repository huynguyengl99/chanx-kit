"""Deepgram Aura streaming text-to-speech behind the synthesizer contract."""

import json
import os
from collections.abc import AsyncIterator
from typing import ClassVar
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from ..audio_stream_out import (
    SpeechFormat,
    SynthesizerTopic,
    SynthesizerUnavailableError,
)

PCM_RATES = (8000, 16000, 24000, 32000, 48000)


class DeepgramSynthesizerTopic(SynthesizerTopic):
    """Deepgram Aura text-to-speech; the key comes from ``DEEPGRAM_API_KEY``."""

    # None reads DEEPGRAM_API_KEY when used, so a .env loaded after import works.
    api_key: ClassVar[str | None] = None
    url: ClassVar[str] = "wss://api.deepgram.com/v1/speak"
    default_voice: ClassVar[str | None] = "aura-2-thalia-en"

    @classmethod
    def key(cls) -> str | None:
        return cls.api_key or os.environ.get("DEEPGRAM_API_KEY")

    @classmethod
    def provider_available(cls) -> bool:
        return bool(cls.key())

    @classmethod
    def speak_url(cls, voice: str, audio: SpeechFormat) -> str:
        if audio.sample_rate not in PCM_RATES or audio.channels != 1:
            raise SynthesizerUnavailableError(
                f"Deepgram produces mono PCM at {', '.join(map(str, PCM_RATES))} Hz."
            )
        query = {
            "model": voice,
            "encoding": "linear16",
            "sample_rate": str(audio.sample_rate),
        }
        return f"{cls.url}?{urlencode(query)}"

    @classmethod
    async def synthesize(
        cls, text: str, voice: str | None, audio: SpeechFormat
    ) -> AsyncIterator[bytes]:
        if not (api_key := cls.key()):
            raise SynthesizerUnavailableError("DEEPGRAM_API_KEY is not set.")
        try:
            socket = await connect(
                cls.speak_url(voice or cls.default_voice or "aura-2-thalia-en", audio),
                additional_headers={"Authorization": f"Token {api_key}"},
                max_size=None,
            )
        except InvalidStatus as error:
            status = error.response.status_code
            raise SynthesizerUnavailableError(
                f"Deepgram refused the connection ({status})."
            ) from error
        except OSError as error:
            raise SynthesizerUnavailableError(
                f"Deepgram is unreachable: {error}"
            ) from error

        async with socket:
            await socket.send(json.dumps({"type": "Speak", "text": text}))
            await socket.send(json.dumps({"type": "Flush"}))
            async for message in socket:
                if isinstance(message, bytes):
                    yield message
                    continue
                event = json.loads(message)
                if event.get("type") == "Flushed":
                    break
                if event.get("type") == "Warning":
                    raise RuntimeError(f"Deepgram: {event.get('description', event)}")
            await socket.send(json.dumps({"type": "Close"}))
