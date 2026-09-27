from collections.abc import AsyncIterator
from typing import Any

import pytest

from ...audio_stream_out import (
    Speak,
    SpeakMessage,
    SpeechFormat,
    SynthesizerTopic,
    SynthesizerUnavailableError,
)
from ...audio_stream_out.tests.contract import (
    PATH,
    SPEAK,
    SynthesizerContract,
    audio_of,
    collect_utterance,
    consumer_for,
    send,
)
from ...chanx_testing import build_app, communicator, receive_until, setup_memory_layer
from ...media_stream_out import InMemoryReplayStore
from ..synthesizer import ElevenLabsSynthesizerTopic
from .fake_stream_input import KEY, Recording, fake_elevenlabs


@pytest.fixture
async def elevenlabs() -> AsyncIterator[
    tuple[type[ElevenLabsSynthesizerTopic], Recording]
]:
    async with fake_elevenlabs() as (url, recording):

        class LocalElevenLabs(ElevenLabsSynthesizerTopic):
            api_key = KEY
            replay_store = InMemoryReplayStore()

        LocalElevenLabs.url = url
        yield LocalElevenLabs, recording


class TestElevenLabsMeetsTheContract(SynthesizerContract):
    @pytest.fixture
    def synthesizer_topic(
        self, elevenlabs: tuple[type[ElevenLabsSynthesizerTopic], Recording]
    ) -> type[SynthesizerTopic]:
        return elevenlabs[0]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")


def app_for(topic: type[SynthesizerTopic]) -> tuple[Any, Any]:
    consumer = consumer_for(topic)
    return build_app({PATH: consumer}), consumer


async def test_the_voice_format_and_text_reach_elevenlabs(
    elevenlabs: tuple[type[ElevenLabsSynthesizerTopic], Recording],
) -> None:
    topic, recording = elevenlabs
    app, consumer = app_for(topic)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await send(comm, SpeakMessage(payload=Speak(text="Xin chao", voice="voice-9")))
        messages = await collect_utterance(comm)

    assert recording.paths == ["/v1/text-to-speech/voice-9/stream-input"]
    assert recording.queries[0]["output_format"] == ["pcm_24000"]
    assert recording.queries[0]["model_id"] == ["eleven_flash_v2_5"]
    assert [m["text"] for m in recording.messages] == [" ", "Xin chao ", ""]
    assert recording.messages[0]["voice_settings"] == topic.voice_settings
    assert len(audio_of(messages)) == 2 * (8 * 24000 // 50)


async def test_a_wrong_key_is_reported(
    elevenlabs: tuple[type[ElevenLabsSynthesizerTopic], Recording],
) -> None:
    class WrongKey(elevenlabs[0]):  # type: ignore[misc, valid-type]
        api_key = "nope"

    app, consumer = app_for(WrongKey)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await send(comm, SpeakMessage(payload=Speak(text="hi")))
        error = await receive_until(comm, "synthesizer_error", timeout=3)

    assert error["payload"]["code"] == "provider_unavailable"
    assert "401" in error["payload"]["message"]


def test_an_unsupported_format_is_refused_up_front() -> None:
    with pytest.raises(SynthesizerUnavailableError):
        ElevenLabsSynthesizerTopic.stream_url("v", SpeechFormat(sample_rate=11025))
    with pytest.raises(SynthesizerUnavailableError):
        ElevenLabsSynthesizerTopic.stream_url("v", SpeechFormat(channels=2))


def test_no_key_means_unavailable() -> None:
    class NoKey(ElevenLabsSynthesizerTopic):
        api_key = None

    assert not NoKey.provider_available()


def test_a_plan_refusal_says_what_to_change() -> None:
    from ..synthesizer import refusal

    assert refusal("payment_required", "v1") == (
        "ElevenLabs: payment_required "
        "(voice v1 is not available on this plan; use a premade voice)"
    )
    assert refusal("something_new", "v1") == "ElevenLabs: something_new"
