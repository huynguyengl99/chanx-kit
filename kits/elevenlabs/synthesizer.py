"""ElevenLabs streaming text-to-speech behind the synthesizer contract."""

import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from ..audio_stream_out import (
    SpeechFormat,
    SynthesizerTopic,
    SynthesizerUnavailableError,
)

PCM_RATES = (8000, 16000, 22050, 24000, 44100, 48000)


def refusal(error: str, voice: str) -> str:
    """ElevenLabs refuses in-band; say what to change."""
    hints = {
        "payment_required": (
            f"voice {voice} is not available on this plan; use a premade voice"
        ),
        "quota_exceeded": "the account's character quota is used up",
    }
    return f"ElevenLabs: {error}" + (f" ({hints[error]})" if error in hints else "")


class ElevenLabsSynthesizerTopic(SynthesizerTopic):
    """ElevenLabs streaming text-to-speech; the key comes from ``ELEVENLABS_API_KEY``."""

    # None reads ELEVENLABS_API_KEY when used, so a .env loaded after import works.
    api_key: ClassVar[str | None] = None
    url: ClassVar[str] = (
        "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
    )
    # Sarah: premade on every plan. Retired voices such as Rachel cost money.
    default_voice: ClassVar[str | None] = "EXAVITQu4vr4xnSDxMaL"
    model_id: ClassVar[str] = "eleven_flash_v2_5"
    voice_settings: ClassVar[dict[str, Any]] = {
        "stability": 0.5,
        "similarity_boost": 0.75,
    }
    options: ClassVar[dict[str, str]] = {}

    @classmethod
    def key(cls) -> str | None:
        return cls.api_key or os.environ.get("ELEVENLABS_API_KEY")

    @classmethod
    def provider_available(cls) -> bool:
        return bool(cls.key())

    @classmethod
    def stream_url(cls, voice: str, audio: SpeechFormat) -> str:
        if audio.sample_rate not in PCM_RATES or audio.channels != 1:
            raise SynthesizerUnavailableError(
                f"ElevenLabs produces mono PCM at {', '.join(map(str, PCM_RATES))} Hz."
            )
        query = {
            "model_id": cls.model_id,
            "output_format": f"pcm_{audio.sample_rate}",
            **cls.options,
        }
        return f"{cls.url.format(voice_id=voice)}?{urlencode(query)}"

    @classmethod
    async def synthesize(
        cls, text: str, voice: str | None, audio: SpeechFormat
    ) -> AsyncIterator[bytes]:
        if not (api_key := cls.key()):
            raise SynthesizerUnavailableError("ELEVENLABS_API_KEY is not set.")
        voice = voice or cls.default_voice
        if not voice:
            raise SynthesizerUnavailableError("No ElevenLabs voice id.")
        try:
            socket = await connect(
                cls.stream_url(voice, audio),
                additional_headers={"xi-api-key": api_key},
                max_size=None,
            )
        except InvalidStatus as error:
            status = error.response.status_code
            raise SynthesizerUnavailableError(
                f"ElevenLabs refused the connection ({status})."
            ) from error
        except OSError as error:
            raise SynthesizerUnavailableError(
                f"ElevenLabs is unreachable: {error}"
            ) from error

        async with socket:
            # The opening message's text is a single space.
            await socket.send(
                json.dumps({"text": " ", "voice_settings": cls.voice_settings})
            )
            await socket.send(json.dumps({"text": f"{text} ", "flush": True}))
            # Empty text ends the input.
            await socket.send(json.dumps({"text": ""}))
            async for raw in socket:
                message = json.loads(raw)
                if error := message.get("error"):
                    raise SynthesizerUnavailableError(refusal(str(error), voice))
                if message.get("audio"):
                    yield base64.b64decode(message["audio"])
                if message.get("isFinal"):
                    break
