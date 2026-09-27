import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from ...chanx_testing import build_app, communicator, receive_until, setup_memory_layer
from ..messages import AudioEndMessage, AudioStart
from ..provider import (
    FinalFrame,
    PartialFrame,
    ProviderUnavailableError,
    SpeechStartedFrame,
    TranscriberFrame,
    UtteranceEndFrame,
)
from ..topics import TranscriberTopic
from .contract import (
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


class ScriptedStream:
    """Hears "hello" in the audio, then "world" once flushed."""

    instances: list["ScriptedStream"] = []

    def __init__(self) -> None:
        self.received = 0
        self.keepalives = 0
        self.closed = False
        self._frames: asyncio.Queue[TranscriberFrame | None] = asyncio.Queue()
        ScriptedStream.instances.append(self)

    async def send(self, audio: bytes) -> None:
        if self.received == 0:
            self._frames.put_nowait(SpeechStartedFrame(at_ms=0))
            self._frames.put_nowait(PartialFrame(text="hel", start_ms=0, end_ms=100))
        self.received += len(audio)

    async def keepalive(self) -> None:
        self.keepalives += 1

    async def finish(self) -> None:
        self._frames.put_nowait(FinalFrame(text="hello", start_ms=0, end_ms=500))
        self._frames.put_nowait(FinalFrame(text="world", start_ms=500, end_ms=1000))
        self._frames.put_nowait(UtteranceEndFrame())
        self._frames.put_nowait(None)

    async def close(self) -> None:
        self.closed = True
        self._frames.put_nowait(None)

    async def frames(self) -> AsyncIterator[TranscriberFrame]:
        while (frame := await self._frames.get()) is not None:
            yield frame


class ScriptedTranscriberTopic(TranscriberTopic):
    async def open_stream(self, audio: AudioStart) -> ScriptedStream:
        return ScriptedStream()


class TestScriptedTranscriberMeetsTheContract(TranscriberContract):
    @pytest.fixture
    def transcriber_topic(self) -> type[TranscriberTopic]:
        return ScriptedTranscriberTopic


@pytest.fixture(autouse=True)
def _streams() -> None:
    setup_memory_layer("default")
    TranscriberTopic._open.clear()
    ScriptedStream.instances.clear()


def app_for(topic: type[TranscriberTopic]) -> tuple[Any, Any]:
    consumer = consumer_for(topic)
    return build_app({PATH: consumer}), consumer


async def test_the_whole_stream_reaches_the_provider() -> None:
    app, consumer = app_for(ScriptedTranscriberTopic)
    audio = speech(5)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await send_audio(comm, audio)
        await send(comm, AudioEndMessage())
        await collect_utterance(comm)

    assert ScriptedStream.instances[0].received == sum(map(len, audio))


async def test_leaving_closes_the_provider_stream() -> None:
    app, consumer = app_for(ScriptedTranscriberTopic)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await send_audio(comm, speech(1))
        await receive_until(comm, "transcript_partial")
        await comm.unsubscribe(TRANSCRIBE)

    assert ScriptedStream.instances[0].closed
    assert TranscriberTopic._open == {}


async def test_a_new_audio_start_replaces_the_stream() -> None:
    app, consumer = app_for(ScriptedTranscriberTopic)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await send_audio(comm, speech(1))
        await receive_until(comm, "transcript_partial")
        await start(comm)
        await send_audio(comm, speech(1))
        await receive_until(comm, "transcript_partial")

        first, second = ScriptedStream.instances
        assert first.closed and not second.closed


async def test_quiet_time_keeps_the_provider_alive() -> None:
    class Chatty(ScriptedTranscriberTopic):
        keepalive_seconds = 0.02

    app, consumer = app_for(Chatty)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await asyncio.sleep(0.15)
        assert ScriptedStream.instances[0].keepalives >= 3


async def test_a_provider_that_refuses_is_reported() -> None:
    class Refusing(TranscriberTopic):
        async def open_stream(self, audio: AudioStart) -> ScriptedStream:
            raise ProviderUnavailableError("bad key")

    app, consumer = app_for(Refusing)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        error = await receive_until(comm, "transcriber_error")

    assert error["payload"] == {"code": "provider_unavailable", "message": "bad key"}
    assert TranscriberTopic._open == {}


async def test_an_unconfigured_provider_says_so_on_subscribe() -> None:
    class NoKey(ScriptedTranscriberTopic):
        def provider_available(self) -> bool:
            return False

    app, consumer = app_for(NoKey)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        error = await receive_until(comm, "transcriber_error")

    assert error["payload"]["code"] == "provider_unavailable"


async def test_final_hooks_see_the_text() -> None:
    seen: list[str] = []

    class Hooked(ScriptedTranscriberTopic):
        async def on_final(self, transcript: Any) -> None:
            seen.append(transcript.text)
            await super().on_final(transcript)

    app, consumer = app_for(Hooked)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await send_audio(comm, speech(2))
        await send(comm, AudioEndMessage())
        await collect_utterance(comm)

    assert seen == ["hello", "world"]


async def test_audio_sent_while_the_provider_connects_is_kept() -> None:
    """Chunks and audio_end right behind audio_start arrive before the stream is open."""

    class SlowToOpen(ScriptedTranscriberTopic):
        async def open_stream(self, audio: AudioStart) -> ScriptedStream:
            await asyncio.sleep(0.1)
            return ScriptedStream()

    app, consumer = app_for(SlowToOpen)
    audio = speech(4)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        await send_audio(comm, audio)
        await send(comm, AudioEndMessage())
        messages = await collect_utterance(comm)

    assert ScriptedStream.instances[0].received == sum(map(len, audio))
    assert [
        m["payload"]["text"] for m in messages if m["action"] == "transcript_final"
    ] == [
        "hello",
        "world",
    ]


async def test_a_provider_crashing_on_open_frees_the_session() -> None:
    class Crashing(TranscriberTopic):
        max_sessions_per_user = 1

        def current_user_id(self) -> str | None:
            return "u"

        async def open_stream(self, audio: AudioStart) -> ScriptedStream:
            raise OSError("dns failure")

    app, consumer = app_for(Crashing)
    async with communicator(app, PATH, consumer) as comm:
        await comm.subscribe(TRANSCRIBE)
        await receive_until(comm, "audio_config")
        await start(comm)
        error = await receive_until(comm, "transcriber_error")
        await send_audio(comm, speech(1))
        after = await receive_until(comm, "transcriber_error")

    assert error["payload"] == {
        "code": "provider_unavailable",
        "message": "dns failure",
    }
    assert after["payload"]["code"] == "not_started"
    assert TranscriberTopic._open == {}
