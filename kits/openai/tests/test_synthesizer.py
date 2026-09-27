import json
from typing import Any, ClassVar

import httpx
import pytest

from ...audio_stream_out import (
    SpeechFormat,
    SynthesizerTopic,
    SynthesizerUnavailableError,
)
from ...audio_stream_out.tests.contract import SynthesizerContract
from ...chanx_testing import setup_memory_layer
from ...media_stream_out import InMemoryReplayStore
from ..synthesizer import OpenAISynthesizerTopic

KEY = "test-key"


class FakeSpeech:
    """OpenAI's speech endpoint, per its documented request and PCM response."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json={"error": {"message": "bad key"}})
        body = json.loads(request.content)
        self.requests.append(body)
        audio = b"\x05\x06" * (len(body["input"]) * 24000 // 50)
        return httpx.Response(200, content=audio, headers={"content-type": "audio/pcm"})


SPEECH = FakeSpeech()


class LocalOpenAI(OpenAISynthesizerTopic):
    api_key = KEY
    replay_store = InMemoryReplayStore()
    transport = httpx.MockTransport(SPEECH)
    instructions: ClassVar[str | None] = "Speak warmly."


class TestOpenAIMeetsTheContract(SynthesizerContract):
    @pytest.fixture
    def synthesizer_topic(self) -> type[SynthesizerTopic]:
        return LocalOpenAI


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")


async def test_the_request_asks_for_raw_pcm() -> None:
    audio = b"".join(
        [
            piece
            async for piece in LocalOpenAI.synthesize("Hello", "nova", SpeechFormat())
        ]
    )

    assert SPEECH.requests[-1] == {
        "model": "gpt-4o-mini-tts",
        "voice": "nova",
        "input": "Hello",
        "response_format": "pcm",
        "instructions": "Speak warmly.",
    }
    assert len(audio) == 2 * (5 * 24000 // 50)


async def test_a_wrong_key_is_unavailable_not_a_crash() -> None:
    class WrongKey(LocalOpenAI):
        api_key = "nope"

    with pytest.raises(SynthesizerUnavailableError, match="401"):
        async for _ in WrongKey.synthesize("Hello", None, SpeechFormat()):
            pass


async def test_only_24_khz_mono_is_offered() -> None:
    with pytest.raises(SynthesizerUnavailableError):
        async for _ in LocalOpenAI.synthesize(
            "Hello", None, SpeechFormat(sample_rate=16000)
        ):
            pass
