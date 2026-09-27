from collections.abc import AsyncIterator
from typing import Any

import pytest

from ...audio_stream_in import AudioEndMessage, AudioStart, TranscriberTopic
from ...audio_stream_in.tests.contract import (
    PATH,
    TRANSCRIBE,
    TranscriberContract,
    consumer_for,
    send,
    send_audio,
    speech,
    start,
)
from ...chanx_testing import build_app, communicator, receive_until, setup_memory_layer
from ..transcriber import DeepgramTranscriberTopic, frames_from
from .fake_listen import KEY, Recording, fake_deepgram


@pytest.fixture
async def deepgram() -> AsyncIterator[tuple[type[DeepgramTranscriberTopic], Recording]]:
    async with fake_deepgram() as (url, recording):

        class LocalDeepgram(DeepgramTranscriberTopic):
            api_key = KEY

        LocalDeepgram.url = url
        yield LocalDeepgram, recording


class TestDeepgramMeetsTheContract(TranscriberContract):
    @pytest.fixture
    def transcriber_topic(
        self, deepgram: tuple[type[DeepgramTranscriberTopic], Recording]
    ) -> type[TranscriberTopic]:
        return deepgram[0]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")
    TranscriberTopic._open.clear()


def app_for(topic: type[TranscriberTopic]) -> tuple[Any, Any]:
    consumer = consumer_for(topic)
    return build_app({PATH: consumer}), consumer


async def test_the_stream_is_opened_with_the_negotiated_format(
    deepgram: tuple[type[DeepgramTranscriberTopic], Recording],
) -> None:
    topic, recording = deepgram
    app, consumer = app_for(topic)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm, language="vi")
        await send_audio(comm, speech(5))
        await send(comm, AudioEndMessage())
        await receive_until(comm, "utterance_end", timeout=3)

    query = recording.queries[0]
    assert query["encoding"] == ["linear16"]
    assert query["sample_rate"] == ["24000"]
    assert query["channels"] == ["1"]
    assert query["interim_results"] == ["true"]
    assert query["language"] == ["vi"]
    assert recording.audio_bytes == 5 * 4800
    assert recording.controls[-2:] == ["Finalize", "CloseStream"]


async def test_a_wrong_key_is_reported_not_raised(
    deepgram: tuple[type[DeepgramTranscriberTopic], Recording],
) -> None:
    class WrongKey(deepgram[0]):  # type: ignore[misc, valid-type]
        api_key = "nope"

    app, consumer = app_for(WrongKey)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        error = await receive_until(comm, "transcriber_error", timeout=3)

    assert error["payload"]["code"] == "provider_unavailable"
    assert "401" in error["payload"]["message"]


async def test_no_key_means_unavailable_on_subscribe() -> None:
    class NoKey(DeepgramTranscriberTopic):
        api_key = None

    app, consumer = app_for(NoKey)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        error = await receive_until(comm, "transcriber_error")

    assert error["payload"]["code"] == "provider_unavailable"


def test_results_map_to_frames() -> None:
    interim = {
        "type": "Results",
        "is_final": False,
        "start": 1.0,
        "duration": 0.5,
        "channel": {"alternatives": [{"transcript": "hi", "confidence": 0.5}]},
    }
    final = interim | {"is_final": True, "speech_final": True}

    assert [type(f).__name__ for f in frames_from(interim)] == ["PartialFrame"]
    assert [type(f).__name__ for f in frames_from(final)] == [
        "FinalFrame",
        "UtteranceEndFrame",
    ]
    assert frames_from(final)[0].end_ms == 1500  # type: ignore[union-attr]
    # Deepgram sends empty results for silence; they are not transcripts.
    empty = interim | {"channel": {"alternatives": [{"transcript": ""}]}}
    assert frames_from(empty) == []
    assert frames_from({"type": "Metadata"}) == []
    assert frames_from({"type": "SpeechStarted", "timestamp": 0.25})[0].at_ms == 250  # type: ignore[union-attr]


async def test_keepalives_are_sent_while_the_user_pauses(
    deepgram: tuple[type[DeepgramTranscriberTopic], Recording],
) -> None:
    import asyncio

    class Chatty(deepgram[0]):  # type: ignore[misc, valid-type]
        keepalive_seconds = 0.05

    app, consumer = app_for(Chatty)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await asyncio.sleep(0.3)

    assert deepgram[1].controls.count("KeepAlive") >= 3


def test_the_default_endpoint_is_deepgram_nova_3() -> None:
    assert DeepgramTranscriberTopic.listen_url(
        DeepgramTranscriberTopic.__new__(DeepgramTranscriberTopic), AudioStart()
    ).startswith("wss://api.deepgram.com/v1/listen?model=nova-3")


def test_the_key_is_read_when_used_so_a_late_dotenv_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    assert DeepgramTranscriberTopic.key() is None
    monkeypatch.setenv("DEEPGRAM_API_KEY", "late")
    assert DeepgramTranscriberTopic.key() == "late"
