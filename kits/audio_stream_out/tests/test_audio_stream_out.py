import asyncio
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest

from ...chanx_testing import (
    build_app,
    communicator,
    receive_json,
    receive_until,
    setup_memory_layer,
)
from ...media_stream_out import InMemoryReplayStore
from ..messages import Speak, SpeakMessage, SpeechFormat
from ..playback import InMemoryPlaybackStore, heard_text
from ..topics import SynthesizerTopic, SynthesizerUnavailableError
from .contract import (
    PATH,
    SESSION,
    SPEAK,
    SynthesizerContract,
    audio_of,
    collect_utterance,
    consumer_for,
    send,
)


class ToneTopic(SynthesizerTopic):
    """10 ms of audio per character, in awkward piece sizes, gated for tests."""

    replay_store = InMemoryReplayStore()
    playback_store = InMemoryPlaybackStore()
    gate: ClassVar[asyncio.Event | None] = None

    @classmethod
    async def synthesize(
        cls, text: str, voice: str | None, audio: SpeechFormat
    ) -> AsyncIterator[bytes]:
        total = len(text) * audio.sample_rate * 2 // 100
        sent = 0
        while sent < total:
            piece = min(777, total - sent)  # odd: splits PCM16 frames
            yield bytes([sent % 251]) * piece
            sent += piece
            if cls.gate is not None and sent > 2000:
                await cls.gate.wait()


class TestToneMeetsTheContract(SynthesizerContract):
    @pytest.fixture
    def synthesizer_topic(self) -> type[SynthesizerTopic]:
        return ToneTopic


@pytest.fixture(autouse=True)
def _layer() -> Any:
    setup_memory_layer("default")
    ToneTopic.replay_store.reset()  # type: ignore[attr-defined]
    ToneTopic.gate = None
    yield
    ToneTopic.gate = None


def app_for(topic: type[SynthesizerTopic]) -> tuple[Any, Any]:
    consumer = consumer_for(topic)
    return build_app({PATH: consumer}), consumer


async def test_audio_is_cut_into_bounded_whole_frames() -> None:
    app, consumer = app_for(ToneTopic)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await send(comm, SpeakMessage(payload=Speak(text="x" * 50)))
        messages = await collect_utterance(comm)

    import base64

    sizes = [
        len(base64.b64decode(m["payload"]["data"]))
        for m in messages
        if m["action"] == "audio_chunk"
    ]
    assert all(size % 2 == 0 for size in sizes)
    assert max(sizes) <= 24000 * 2 * 200 // 1000
    assert sum(sizes) == 50 * 24000 * 2 // 100


async def test_a_listener_joining_mid_utterance_is_replayed_from_its_start() -> None:
    ToneTopic.gate = asyncio.Event()
    app, consumer = app_for(ToneTopic)
    async with communicator(app, PATH, consumer) as first:
        await first.subscribe(SPEAK)
        await ToneTopic.speak(SESSION, "y" * 30, utterance_id="u")
        await receive_until(first, "audio_chunk")

        async with communicator(app, PATH, consumer) as late:
            await late.subscribe(SPEAK)
            [replayed] = await receive_json(late, 1)
            assert replayed["action"] == "audio_start"
            assert replayed["seq"] == 1
            ToneTopic.gate.set()
            late_messages = [replayed, *await collect_utterance(late)]

        first_messages = await collect_utterance(first)

    indexes = [
        m["payload"]["index"] for m in late_messages if m["action"] == "audio_chunk"
    ]
    assert indexes == sorted(set(indexes)) == list(range(len(indexes)))
    assert len(audio_of(late_messages)) == 30 * 24000 * 2 // 100
    assert first_messages[-1]["action"] == "audio_end"


async def test_clear_stops_the_utterance_and_drops_the_queue() -> None:
    ToneTopic.gate = asyncio.Event()
    app, consumer = app_for(ToneTopic)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await ToneTopic.speak(SESSION, "z" * 30, utterance_id="playing")
        await ToneTopic.speak(SESSION, "queued", utterance_id="queued")
        await receive_until(comm, "audio_chunk")

        await ToneTopic.clear(SESSION)
        cleared = await receive_until(comm, "clear")

        assert cleared["payload"] == {"utterance_id": "playing"}
        assert not ToneTopic.is_speaking(SESSION)
        await ToneTopic.speak(SESSION, "fresh", utterance_id="fresh")
        after = await receive_until(comm, "audio_start")

    assert after["payload"]["utterance_id"] == "fresh"


async def test_text_over_the_limit_is_refused() -> None:
    class Short(ToneTopic):
        max_text_chars = 5

    app, consumer = app_for(Short)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await send(comm, SpeakMessage(payload=Speak(text="too long")))
        error = await receive_until(comm, "synthesizer_error")

    assert error["payload"]["code"] == "bad_request"


async def test_a_refusing_provider_is_reported_and_the_utterance_still_ends() -> None:
    class Refusing(ToneTopic):
        @classmethod
        async def synthesize(
            cls, text: str, voice: str | None, audio: SpeechFormat
        ) -> AsyncIterator[bytes]:
            raise SynthesizerUnavailableError("bad key")
            yield b""  # pragma: no cover

    app, consumer = app_for(Refusing)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await send(comm, SpeakMessage(payload=Speak(text="hi", utterance_id="u")))
        error = await receive_until(comm, "synthesizer_error")
        end = await receive_until(comm, "audio_end")

    assert error["payload"] == {
        "code": "provider_unavailable",
        "message": "bad key",
        "utterance_id": "u",
    }
    assert end["payload"]["duration_ms"] == 0


async def test_an_unconfigured_provider_answers_the_asker() -> None:
    class NoKey(ToneTopic):
        @classmethod
        def provider_available(cls) -> bool:
            return False

    app, consumer = app_for(NoKey)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(SPEAK)
        await send(comm, SpeakMessage(payload=Speak(text="hi")))
        error = await receive_until(comm, "synthesizer_error")

    assert error["payload"]["code"] == "provider_unavailable"


@pytest.mark.parametrize(
    ("played", "heard"),
    [
        (0, ""),
        (500, "The quick brown"),
        (1000, "The quick brown fox jumps over"),
        (5000, "The quick brown fox jumps over"),
    ],
)
def test_heard_text_cuts_at_a_word(played: int, heard: str) -> None:
    assert heard_text("The quick brown fox jumps over", 1000, played) == heard


def test_heard_text_of_an_unmeasured_utterance_is_empty() -> None:
    assert heard_text("anything", 0, 100) == ""
