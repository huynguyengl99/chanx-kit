"""OpenAI text-to-speech behind the synthesizer contract."""

import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx

from ..audio_stream_out import (
    SpeechFormat,
    SynthesizerTopic,
    SynthesizerUnavailableError,
)

# The `pcm` response format is fixed: 24 kHz, 16-bit, mono.
PCM_RATE = 24000


class OpenAISynthesizerTopic(SynthesizerTopic):
    """OpenAI text-to-speech as streamed PCM; the key comes from ``OPENAI_API_KEY``."""

    # None reads OPENAI_API_KEY when used, so a .env loaded after import works.
    api_key: ClassVar[str | None] = None
    url: ClassVar[str] = "https://api.openai.com/v1/audio/speech"
    model: ClassVar[str] = "gpt-4o-mini-tts"
    default_voice: ClassVar[str | None] = "alloy"
    # Tone, pace, accent.
    instructions: ClassVar[str | None] = None
    # Swapped in tests.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    @classmethod
    def key(cls) -> str | None:
        return cls.api_key or os.environ.get("OPENAI_API_KEY")

    @classmethod
    def provider_available(cls) -> bool:
        return bool(cls.key())

    @classmethod
    async def synthesize(
        cls, text: str, voice: str | None, audio: SpeechFormat
    ) -> AsyncIterator[bytes]:
        if not (api_key := cls.key()):
            raise SynthesizerUnavailableError("OPENAI_API_KEY is not set.")
        if audio.sample_rate != PCM_RATE or audio.channels != 1:
            raise SynthesizerUnavailableError("OpenAI speech is PCM16 mono at 24 kHz.")
        body: dict[str, Any] = {
            "model": cls.model,
            "voice": voice or cls.default_voice or "alloy",
            "input": text,
            "response_format": "pcm",
        }
        if cls.instructions:
            body["instructions"] = cls.instructions
        async with (
            httpx.AsyncClient(transport=cls.transport, timeout=60) as client,
            client.stream(
                "POST",
                cls.url,
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            ) as response,
        ):
            if response.status_code in (
                httpx.codes.UNAUTHORIZED,
                httpx.codes.FORBIDDEN,
            ):
                raise SynthesizerUnavailableError(
                    f"OpenAI refused the request ({response.status_code})."
                )
            if response.is_error:
                detail = (await response.aread()).decode(errors="replace")[:200]
                raise RuntimeError(
                    f"OpenAI speech failed ({response.status_code}): {detail}"
                )
            async for piece in response.aiter_bytes():
                yield piece
