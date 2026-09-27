from collections.abc import AsyncIterator
from typing import Any

import pytest

from ...audio_stream_in import (
    AudioEndMessage,
    AudioStart,
    ProviderUnavailableError,
    TranscriberTopic,
)
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
from ...chanx_testing import (
    build_app,
    communicator,
    receive_json,
    receive_until,
    setup_memory_layer,
)
from ..transcriber import ElevenLabsTranscriberTopic
from .fake_scribe import KEY, Recording, fake_scribe


@pytest.fixture
async def scribe() -> AsyncIterator[tuple[type[ElevenLabsTranscriberTopic], Recording]]:
    async with fake_scribe() as (url, recording):

        class LocalScribe(ElevenLabsTranscriberTopic):
            api_key = KEY

        LocalScribe.url = url
        yield LocalScribe, recording


class TestElevenLabsMeetsTheContract(TranscriberContract):
    @pytest.fixture
    def transcriber_topic(
        self, scribe: tuple[type[ElevenLabsTranscriberTopic], Recording]
    ) -> type[TranscriberTopic]:
        return scribe[0]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")
    TranscriberTopic._open.clear()


async def test_the_format_and_language_reach_scribe(
    scribe: tuple[type[ElevenLabsTranscriberTopic], Recording],
) -> None:
    topic, recording = scribe
    consumer = consumer_for(topic)
    app: Any = build_app({PATH: consumer})
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm, language="vi")
        await send_audio(comm, speech(5))
        await send(comm, AudioEndMessage())
        await receive_until(comm, "utterance_end", timeout=3)

    query = recording.queries[0]
    assert query["audio_format"] == ["pcm_24000"]
    assert query["commit_strategy"] == ["vad"]
    assert query["language_code"] == ["vi"]
    assert query["model_id"] == ["scribe_v2_realtime"]
    assert recording.audio_bytes == 5 * 4800
    assert recording.commits == 1


def test_an_unsupported_format_is_refused() -> None:
    topic = ElevenLabsTranscriberTopic.__new__(ElevenLabsTranscriberTopic)
    with pytest.raises(ProviderUnavailableError):
        topic.realtime_url(AudioStart(sample_rate=11025))


async def test_the_first_partial_of_an_utterance_reports_speech(
    scribe: tuple[type[ElevenLabsTranscriberTopic], Recording],
) -> None:
    consumer = consumer_for(scribe[0])
    app: Any = build_app({PATH: consumer})
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await send_audio(comm, speech(5))
        started = await receive_until(comm, "speech_started", timeout=3)
        [partial] = await receive_json(comm, 1, timeout=3)

    assert started["payload"] == {"at_ms": 0}
    assert partial["action"] == "transcript_partial"
