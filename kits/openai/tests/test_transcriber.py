from collections.abc import AsyncIterator
from typing import Any

import pytest

from ...audio_stream_in import AudioEndMessage, TranscriberTopic
from ...audio_stream_in.tests.contract import (
    PATH,
    TRANSCRIBE,
    TranscriberContract,
    collect_utterance,
    consumer_for,
    send,
    send_audio,
    speech,
    start,
)
from ...chanx_testing import build_app, communicator, receive_until, setup_memory_layer
from ..transcriber import OpenAITranscriberTopic
from .fake_realtime import KEY, Recording, fake_realtime


@pytest.fixture
async def realtime() -> AsyncIterator[tuple[type[OpenAITranscriberTopic], Recording]]:
    async with fake_realtime() as (url, recording):

        class LocalRealtime(OpenAITranscriberTopic):
            api_key = KEY

        LocalRealtime.url = url
        yield LocalRealtime, recording


class TestOpenAIMeetsTheContract(TranscriberContract):
    @pytest.fixture
    def transcriber_topic(
        self, realtime: tuple[type[OpenAITranscriberTopic], Recording]
    ) -> type[TranscriberTopic]:
        return realtime[0]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")
    TranscriberTopic._open.clear()


def app_for(topic: type[TranscriberTopic]) -> tuple[Any, Any]:
    consumer = consumer_for(topic)
    return build_app({PATH: consumer}), consumer


async def test_the_session_is_configured_for_transcription(
    realtime: tuple[type[OpenAITranscriberTopic], Recording],
) -> None:
    topic, recording = realtime
    app, consumer = app_for(topic)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm, language="en")
        await send_audio(comm, speech(5))
        await send(comm, AudioEndMessage())
        messages = await collect_utterance(comm)

    session = recording.sessions[0]
    assert session["type"] == "transcription"
    assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert session["audio"]["input"]["transcription"] == {
        "model": "gpt-live-transcribe",
        "language": "en",
    }
    assert session["audio"]["input"]["turn_detection"] is None
    assert recording.commits == 1
    partials = [
        m["payload"]["text"] for m in messages if m["action"] == "transcript_partial"
    ]
    assert partials == ["hello", "hello world"]


async def test_ending_without_speech_is_not_an_error(
    realtime: tuple[type[OpenAITranscriberTopic], Recording],
) -> None:
    app, consumer = app_for(realtime[0])
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await send_audio(comm, speech(1))
        await send(comm, AudioEndMessage())
        await start(comm)
        await send_audio(comm, speech(5))
        await send(comm, AudioEndMessage())
        messages = await collect_utterance(comm)

    assert [
        m["payload"]["text"] for m in messages if m["action"] == "transcript_final"
    ] == ["hello world"]
