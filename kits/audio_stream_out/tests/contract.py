"""The synthesizer@1 suite: subclass ``SynthesizerContract`` and provide ``synthesizer_topic``."""

import base64
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
from ...media_stream_out import InMemoryReplayStore
from ..messages import (
    PlaybackMark,
    PlaybackMarkMessage,
    Speak,
    SpeakClearMessage,
    SpeakMessage,
)
from ..playback import InMemoryPlaybackStore
from ..topics import SynthesizerTopic

PATH = "/ws/speech"
SESSION = "s1"
SPEAK = f"speak:{SESSION}"


async def send(comm: Any, message: BaseMessage, topic: str = SPEAK) -> None:
    """Like ``comm.send_message``, which dumps in Python mode and so cannot carry bytes."""
    await comm.send_json_to(
        message.model_dump(mode="json") | {"version": ENVELOPE_VERSION, "topic": topic}
    )


def consumer_for(topic: type[SynthesizerTopic]) -> Any:
    class SpeechConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [topic]

    return SpeechConsumer


async def collect_utterance(comm: Any, timeout: float = 5) -> list[dict[str, Any]]:
    """An utterance's messages, audio_start to audio_end."""
    seen: list[dict[str, Any]] = []
    for _ in range(2000):
        [message] = await receive_json(comm, 1, timeout)
        if message["action"] == "synthesizer_error":
            raise AssertionError(f"synthesizer_error: {message['payload']}")
        seen.append(message)
        if message["action"] == "audio_end":
            return seen
    raise AssertionError("no audio_end")


def audio_of(messages: list[dict[str, Any]]) -> bytes:
    return b"".join(
        base64.b64decode(m["payload"]["data"])
        for m in messages
        if m["action"] == "audio_chunk"
    )


class SynthesizerContract:
    @pytest.fixture(autouse=True)
    def _contract_layer(self, synthesizer_topic: type[SynthesizerTopic]) -> None:
        setup_memory_layer("default")
        if isinstance(synthesizer_topic.replay_store, InMemoryReplayStore):
            synthesizer_topic.replay_store.reset()
        if isinstance(synthesizer_topic.playback_store, InMemoryPlaybackStore):
            synthesizer_topic.playback_store.reset()

    @pytest.fixture
    def synthesizer_topic(self) -> type[SynthesizerTopic]:
        raise NotImplementedError("provide a synthesizer_topic fixture")

    def app_for(self, topic: type[SynthesizerTopic]) -> tuple[Any, Any]:
        consumer = consumer_for(topic)
        return build_app({PATH: consumer}), consumer

    async def test_text_becomes_one_utterance_of_pcm_audio(
        self, synthesizer_topic: type[SynthesizerTopic]
    ) -> None:
        app, consumer = self.app_for(synthesizer_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(SPEAK)
            await send(
                comm,
                SpeakMessage(payload=Speak(text="Hello there.", utterance_id="u1")),
            )
            messages = await collect_utterance(comm)

        start, *chunks, end = messages
        fmt = synthesizer_topic.output_format
        assert start["action"] == "audio_start"
        assert start["payload"] == {
            "utterance_id": "u1",
            "text": "Hello there.",
            "encoding": "pcm16",
            "sample_rate": fmt.sample_rate,
            "channels": fmt.channels,
        }
        assert chunks, "no audio"
        assert [c["payload"]["index"] for c in chunks] == list(range(len(chunks)))
        assert {c["payload"]["utterance_id"] for c in chunks} == {"u1"}
        audio = audio_of(messages)
        assert len(audio) % (2 * fmt.channels) == 0, "PCM16 frames are never split"
        assert end["payload"]["utterance_id"] == "u1"
        assert end["payload"]["duration_ms"] == len(audio) * 1000 // (
            fmt.sample_rate * 2 * fmt.channels
        )

    async def test_utterances_play_in_the_order_they_were_queued(
        self, synthesizer_topic: type[SynthesizerTopic]
    ) -> None:
        app, consumer = self.app_for(synthesizer_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(SPEAK)
            for n in (1, 2, 3):
                await send(
                    comm,
                    SpeakMessage(
                        payload=Speak(text=f"Sentence {n}.", utterance_id=f"u{n}")
                    ),
                )
            order = [
                (await collect_utterance(comm))[0]["payload"]["utterance_id"]
                for _ in range(3)
            ]

        assert order == ["u1", "u2", "u3"]

    async def test_a_server_can_speak_without_a_client_asking(
        self, synthesizer_topic: type[SynthesizerTopic]
    ) -> None:
        app, consumer = self.app_for(synthesizer_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(SPEAK)
            utterance = await synthesizer_topic.speak(SESSION, "From the server.")
            messages = await collect_utterance(comm)

        assert messages[0]["payload"]["utterance_id"] == utterance

    async def test_every_listener_hears_it(
        self, synthesizer_topic: type[SynthesizerTopic]
    ) -> None:
        app, consumer = self.app_for(synthesizer_topic)
        async with (
            communicator(app, PATH, consumer) as first,
            communicator(app, PATH, consumer) as second,
        ):
            await first.subscribe(SPEAK)
            await second.subscribe(SPEAK)
            await send(first, SpeakMessage(payload=Speak(text="Both of you.")))
            heard = [
                audio_of(await collect_utterance(comm)) for comm in (first, second)
            ]

        assert heard[0] and heard[0] == heard[1]

    async def test_clear_is_sent_to_listeners(
        self, synthesizer_topic: type[SynthesizerTopic]
    ) -> None:
        app, consumer = self.app_for(synthesizer_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(SPEAK)
            await send(comm, SpeakClearMessage())
            cleared = await receive_until(comm, "clear")
            await send(
                comm, SpeakMessage(payload=Speak(text="Again.", utterance_id="after"))
            )
            messages = await collect_utterance(comm)

        assert cleared["payload"] == {"utterance_id": None}
        assert messages[0]["payload"]["utterance_id"] == "after"

    async def test_empty_text_is_refused(
        self, synthesizer_topic: type[SynthesizerTopic]
    ) -> None:
        app, consumer = self.app_for(synthesizer_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(SPEAK)
            await send(comm, SpeakMessage(payload=Speak(text="   ")))
            error = await receive_until(comm, "synthesizer_error")

        assert error["payload"]["code"] == "bad_request"

    async def test_playback_marks_are_recorded(
        self, synthesizer_topic: type[SynthesizerTopic]
    ) -> None:
        app, consumer = self.app_for(synthesizer_topic)
        async with communicator(app, PATH, consumer) as comm:
            await comm.subscribe(SPEAK)
            await send(
                comm, SpeakMessage(payload=Speak(text="Mark me.", utterance_id="m"))
            )
            await collect_utterance(comm)
            await send(
                comm,
                PlaybackMarkMessage(
                    payload=PlaybackMark(utterance_id="m", played_ms=120)
                ),
            )
            await synthesizer_topic.wait_until_spoken(SESSION)
            # A reply confirms the mark was handled before we read the store.
            await send(comm, SpeakMessage(payload=Speak(text="   ")))
            await receive_until(comm, "synthesizer_error")

        utterance = await synthesizer_topic.playback_store.get(SESSION, "m")
        assert utterance is not None
        assert utterance.text == "Mark me."
        assert utterance.played_ms == 120
        assert utterance.finished
