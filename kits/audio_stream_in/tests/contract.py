"""The transcriber@1 suite: subclass ``TranscriberContract`` and provide ``transcriber_topic``."""

from typing import Any, ClassVar

import pytest
from chanx.constants import ENVELOPE_VERSION
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage

from ...chanx_testing import (
    KitConsumer,
    build_app,
    communicator,
    receive_json,
    receive_until,
    setup_memory_layer,
)
from ..messages import (
    AudioChunk,
    AudioChunkMessage,
    AudioEndMessage,
    AudioStart,
    AudioStartMessage,
)
from ..topics import TranscriberTopic

PATH = "/ws/voice"
SESSION = "s1"
TRANSCRIBE = f"transcribe:{SESSION}"
TRANSCRIPT = f"transcript:{SESSION}"


def speech(
    chunks: int = 10, chunk_ms: int = 100, sample_rate: int = 24000
) -> list[bytes]:
    """PCM16 mono chunks: a quiet tone, so providers that check for audio see some."""
    import math
    import struct

    samples = sample_rate * chunk_ms // 1000
    out: list[bytes] = []
    for chunk in range(chunks):
        frames = (
            int(
                3000 * math.sin(2 * math.pi * 220 * (chunk * samples + i) / sample_rate)
            )
            for i in range(samples)
        )
        out.append(struct.pack(f"<{samples}h", *frames))
    return out


async def send(comm: Any, message: BaseMessage, topic: str = TRANSCRIBE) -> None:
    """Like ``comm.send_message``, which dumps in Python mode and so cannot carry bytes."""
    await comm.send_json_to(
        message.model_dump(mode="json") | {"version": ENVELOPE_VERSION, "topic": topic}
    )


def consumer_for(topic: type[TranscriberTopic]) -> Any:
    class ContractConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [topic, topic.transcript_topic]

    return ContractConsumer


async def start(comm: Any, **overrides: Any) -> None:
    await send(comm, AudioStartMessage(payload=AudioStart(**overrides)))


async def send_audio(comm: Any, chunks: list[bytes]) -> None:
    for index, data in enumerate(chunks):
        await send(comm, AudioChunkMessage(payload=AudioChunk(index=index, data=data)))


async def collect_utterance(comm: Any, timeout: float = 5) -> list[dict[str, Any]]:
    """Transcript messages up to and including the utterance_end."""
    seen: list[dict[str, Any]] = []
    for _ in range(200):
        [message] = await receive_json(comm, 1, timeout)
        seen.append(message)
        if message["action"] == "utterance_end":
            return seen
        if message["action"] == "transcriber_error":
            raise AssertionError(f"transcriber_error: {message['payload']}")
    raise AssertionError("no utterance_end")


class TranscriberContract:
    expected_text: ClassVar[str] = "hello world"

    @pytest.fixture(autouse=True)
    def _contract_layer(self) -> None:
        setup_memory_layer("default")
        TranscriberTopic._open.clear()

    @pytest.fixture
    def transcriber_topic(self) -> type[TranscriberTopic]:
        raise NotImplementedError("provide a transcriber_topic fixture")

    def app_for(self, topic: type[TranscriberTopic]) -> tuple[Any, Any]:
        consumer = consumer_for(topic)
        return build_app({PATH: consumer}), consumer

    async def test_the_format_is_sent_on_subscribe(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        app, consumer = self.app_for(transcriber_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(TRANSCRIBE)
            config = (await receive_json(comm, 1))[0]

        assert config["action"] == "audio_config"
        assert config["payload"] == transcriber_topic.audio_config.model_dump()

    async def test_speech_becomes_an_utterance(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        app, consumer = self.app_for(transcriber_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(TRANSCRIBE)
            await receive_until(comm, "audio_config")
            await start(comm)
            await send_audio(comm, speech())
            await send(comm, AudioEndMessage())
            messages = await collect_utterance(comm)

        finals = [m["payload"] for m in messages if m["action"] == "transcript_final"]
        assert " ".join(f["text"] for f in finals).strip() == self.expected_text
        utterances = {
            m["payload"]["utterance_id"]
            for m in messages
            if m["action"]
            in {"transcript_partial", "transcript_final", "utterance_end"}
        }
        assert len(utterances) == 1, "one utterance, one id"
        for final in finals:
            assert 0 <= final["start_ms"] <= final["end_ms"]

    async def test_watchers_receive_the_transcript(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        app, consumer = self.app_for(transcriber_topic)
        async with (
            communicator(app, PATH, consumer) as speaker,
            communicator(app, PATH, consumer) as watcher,
        ):
            await watcher.subscribe(TRANSCRIPT)
            await speaker.subscribe(TRANSCRIBE)
            await receive_until(speaker, "audio_config")
            await start(speaker)
            await send_audio(speaker, speech())
            await send(speaker, AudioEndMessage())
            await collect_utterance(speaker)
            watched = await collect_utterance(watcher)

        finals = [
            m["payload"]["text"] for m in watched if m["action"] == "transcript_final"
        ]
        assert " ".join(finals).strip() == self.expected_text
        assert {m["topic"] for m in watched} == {TRANSCRIPT}

    async def test_a_format_other_than_the_configured_one_is_refused(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        app, consumer = self.app_for(transcriber_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(TRANSCRIBE)
            await receive_until(comm, "audio_config")
            await start(comm, sample_rate=8000)
            error = await receive_until(comm, "transcriber_error")

        assert error["payload"]["code"] == "bad_format"

    async def test_audio_before_audio_start_is_refused(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        app, consumer = self.app_for(transcriber_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(TRANSCRIBE)
            await receive_until(comm, "audio_config")
            await send_audio(comm, speech(1))
            error = await receive_until(comm, "transcriber_error")

        assert error["payload"]["code"] == "not_started"

    async def test_lost_chunks_are_reported(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        app, consumer = self.app_for(transcriber_topic)
        audio = speech(12)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(TRANSCRIBE)
            await receive_until(comm, "audio_config")
            await start(comm)
            await send(
                comm, AudioChunkMessage(payload=AudioChunk(index=0, data=audio[0]))
            )
            # 1 and 2 never arrive; the sequencer gives up once its window is full.
            for index in range(3, 3 + transcriber_topic.reorder_window + 1):
                await send(
                    comm,
                    AudioChunkMessage(
                        payload=AudioChunk(index=index, data=audio[index % 12])
                    ),
                )
            error = await receive_until(comm, "transcriber_error")

        assert error["payload"]["code"] == "audio_gap"
        assert "1 to 2" in error["payload"]["message"]

    async def test_streams_per_user_are_limited(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        class OneEach(transcriber_topic):  # type: ignore[misc, valid-type]
            max_sessions_per_user = 1

            def current_user_id(self) -> str | None:
                return "same-user"

        app, consumer = self.app_for(OneEach)
        async with (
            communicator(app, PATH, consumer) as first,
            communicator(app, PATH, consumer) as second,
        ):
            for comm in (first, second):
                await comm.subscribe(TRANSCRIBE)
                await receive_until(comm, "audio_config")
            await start(first)
            await send_audio(first, speech(1))
            await start(second)
            error = await receive_until(second, "transcriber_error")

        assert error["payload"]["code"] == "limit_reached"

    async def test_a_silent_stream_is_closed(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        class QuickIdle(transcriber_topic):  # type: ignore[misc, valid-type]
            idle_timeout_seconds = 0.2
            keepalive_seconds = 0.05

        app, consumer = self.app_for(QuickIdle)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(TRANSCRIBE)
            await receive_until(comm, "audio_config")
            await start(comm)
            error = await receive_until(comm, "transcriber_error", timeout=2)

        assert error["payload"]["code"] == "limit_reached"

    async def test_a_stream_is_bounded_in_time(
        self, transcriber_topic: type[TranscriberTopic]
    ) -> None:
        class Short(transcriber_topic):  # type: ignore[misc, valid-type]
            max_session_seconds = 0.2
            idle_timeout_seconds = None

        app, consumer = self.app_for(Short)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(TRANSCRIBE)
            await receive_until(comm, "audio_config")
            await start(comm)
            error = await receive_until(comm, "transcriber_error", timeout=2)

        assert error["payload"]["code"] == "limit_reached"
        assert "seconds" in error["payload"]["message"]
