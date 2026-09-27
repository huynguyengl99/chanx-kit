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
from ...chanx_testing import build_app, communicator, setup_memory_layer
from ...media_stream_out import InMemoryReplayStore
from ..synthesizer import DeepgramSynthesizerTopic
from .fake_speak import KEY, Recording, fake_speak


@pytest.fixture
async def aura() -> AsyncIterator[tuple[type[DeepgramSynthesizerTopic], Recording]]:
    async with fake_speak() as (url, recording):

        class LocalAura(DeepgramSynthesizerTopic):
            api_key = KEY
            replay_store = InMemoryReplayStore()

        LocalAura.url = url
        yield LocalAura, recording


class TestDeepgramMeetsTheContract(SynthesizerContract):
    @pytest.fixture
    def synthesizer_topic(
        self, aura: tuple[type[DeepgramSynthesizerTopic], Recording]
    ) -> type[SynthesizerTopic]:
        return aura[0]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")


async def test_the_voice_and_format_reach_deepgram(
    aura: tuple[type[DeepgramSynthesizerTopic], Recording],
) -> None:
    topic, recording = aura
    consumer = consumer_for(topic)
    app: Any = build_app({PATH: consumer})
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await send(
            comm, SpeakMessage(payload=Speak(text="Hi there", voice="aura-2-luna-en"))
        )
        messages = await collect_utterance(comm)

    assert recording.queries[0] == {
        "model": ["aura-2-luna-en"],
        "encoding": ["linear16"],
        "sample_rate": ["24000"],
    }
    assert [m["type"] for m in recording.messages] == ["Speak", "Flush", "Close"]
    assert len(audio_of(messages)) == 2 * (8 * 24000 // 50)


def test_an_unsupported_format_is_refused() -> None:
    with pytest.raises(SynthesizerUnavailableError):
        DeepgramSynthesizerTopic.speak_url("v", SpeechFormat(sample_rate=22050))
