import asyncio
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
from chanx.core.topic import Topic

from ag_ui.core import (
    Event,
    EventType,
    RunAgentInput,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

from ...ag_ui import InMemoryActiveRunStore, InMemoryRunEventStore
from ...audio_stream_in import AudioEndMessage, TranscriberTopic
from ...audio_stream_in.tests.contract import send, send_audio, speech, start
from ...audio_stream_out import InMemoryPlaybackStore, PlaybackMark, PlaybackMarkMessage
from ...chanx_testing import (
    KitConsumer,
    build_app,
    communicator,
    receive_until,
    setup_memory_layer,
)
from ...fake_voice.synthesizer import FakeSynthesizerTopic
from ...fake_voice.transcriber import FakeTranscriberTopic
from ...media_stream_out import InMemoryReplayStore
from ..memory import InMemoryVoiceMemory
from ..sentences import SentenceBuffer
from ..topics import VoiceAgentTopic, VoiceTranscriberTopic

PATH = "/ws/voice"
SESSION = "s1"


class Voice(FakeSynthesizerTopic):
    pace = 0
    replay_store = InMemoryReplayStore()
    playback_store = InMemoryPlaybackStore()


class Agent(VoiceAgentTopic):
    synthesizer = Voice
    memory = InMemoryVoiceMemory()
    run_event_store = InMemoryRunEventStore()
    active_run_store = InMemoryActiveRunStore()
    seen: ClassVar[list[RunAgentInput]] = []
    gate: ClassVar[asyncio.Event | None] = None

    async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        self.seen.append(run_input)
        yield TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START, message_id="reply"
        )
        for index, delta in enumerate(
            ["Sure, I can help ", "with that today. ", "Anything else?"]
        ):
            yield TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT, message_id="reply", delta=delta
            )
            # Paused after the first sentence is complete, when a test holds the gate.
            if index == 1 and self.gate is not None:
                await self.gate.wait()
        yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id="reply")


class Ears(VoiceTranscriberTopic, FakeTranscriberTopic):
    agent_topic = Agent
    script: ClassVar[list[str]] = ["book", "a", "table"]
    ms_per_word = 300
    words_per_final = 2


class VoiceConsumer(KitConsumer):
    channel_layer_alias = "default"
    topics: ClassVar[list[type[Topic[Any]]]] = [Ears, Agent, Voice]


@pytest.fixture(autouse=True)
def _reset() -> Any:
    setup_memory_layer("default")
    TranscriberTopic._open.clear()
    Agent.memory.reset()  # type: ignore[attr-defined]
    Agent.run_event_store.reset()  # type: ignore[attr-defined]
    Agent.active_run_store.reset()  # type: ignore[attr-defined]
    Voice.replay_store.reset()  # type: ignore[attr-defined]
    Voice.playback_store.reset()  # type: ignore[attr-defined]
    Agent.seen = []
    Agent.gate = None
    Agent._spoken.clear()
    Agent._reply.clear()
    yield
    Agent.gate = None


@pytest.fixture
def app() -> Any:
    return build_app({PATH: VoiceConsumer})


async def collect_utterances(comm: Any, count: int) -> list[str]:
    texts: list[str] = []
    while len(texts) < count:
        message = await receive_until(comm, "audio_start", timeout=3, limit=500)
        texts.append(message["payload"]["text"])
    return texts


async def speak_to_agent(comm: Any) -> None:
    await start(comm)
    await send_audio(comm, speech(10))
    await send(comm, AudioEndMessage())


async def test_what_the_user_says_is_answered_out_loud(app: Any) -> None:
    async with communicator(app, PATH, VoiceConsumer) as comm:
        await comm.subscribe(f"speak:{SESSION}", ref="speak")
        await comm.subscribe(f"transcribe:{SESSION}", ref="ears")
        await receive_until(comm, "audio_config")
        await speak_to_agent(comm)

        spoken = await collect_utterances(comm, 2)
        await Voice.wait_until_spoken(SESSION)

    # One second of audio at 300 ms a word: "book a table".
    assert Agent.seen[0].messages[-1].content == "book a table"
    assert spoken == ["Sure, I can help with that today.", "Anything else?"]


async def test_the_conversation_is_remembered_between_turns(app: Any) -> None:
    await Agent.respond(SESSION, "first question")
    await asyncio.sleep(0.05)
    await Voice.wait_until_spoken(SESSION)
    await Agent.respond(SESSION, "second question")
    await asyncio.sleep(0.05)

    second = Agent.seen[1].messages
    assert [(m.role, m.content) for m in second] == [
        ("user", "first question"),
        ("assistant", "Sure, I can help with that today. Anything else?"),
        ("user", "second question"),
    ]


async def test_a_provider_keeping_its_own_history_gets_the_new_turn_only() -> None:
    class Stateful(Agent):
        send_history = False

    await Stateful.respond(SESSION, "one")
    await asyncio.sleep(0.05)
    await Stateful.respond(SESSION, "two")
    await asyncio.sleep(0.05)
    assert [m.content for m in Stateful.seen[-1].messages] == ["two"]


async def test_speaking_over_the_agent_interrupts_it(app: Any) -> None:
    Agent.gate = asyncio.Event()
    async with communicator(app, PATH, VoiceConsumer) as comm:
        await comm.subscribe(f"speak:{SESSION}", ref="speak")
        await comm.subscribe(f"agui:thread:{SESSION}", ref="thread")
        await Agent.respond(SESSION, "tell me a story")
        first = await receive_until(comm, "audio_start", timeout=3, limit=500)
        end = await receive_until(comm, "audio_end", timeout=3, limit=500)
        half = end["payload"]["duration_ms"] // 2
        await send(
            comm,
            PlaybackMarkMessage(
                payload=PlaybackMark(
                    utterance_id=first["payload"]["utterance_id"], played_ms=half
                )
            ),
            topic=f"speak:{SESSION}",
        )
        await asyncio.sleep(0.05)
        assert Agent.running(SESSION)

        heard = await Agent.interrupt(SESSION)
        cleared = await receive_until(comm, "clear", timeout=3, limit=500)

    assert cleared["payload"]["utterance_id"] in {
        None,
        first["payload"]["utterance_id"],
    }
    assert heard and "Sure, I can help with that today.".startswith(heard)
    assert heard != "Sure, I can help with that today."
    assert not Agent.running(SESSION)
    turns = await Agent.memory.load(SESSION)
    assert [(t.role, t.content) for t in turns] == [
        ("user", "tell me a story"),
        ("assistant", heard),
    ]


async def test_interrupting_a_quiet_agent_does_nothing() -> None:
    assert await Agent.interrupt(SESSION) is None


async def test_speech_starting_triggers_the_interrupt(app: Any) -> None:
    Agent.gate = asyncio.Event()
    async with communicator(app, PATH, VoiceConsumer) as comm:
        await comm.subscribe(f"speak:{SESSION}", ref="speak")
        await comm.subscribe(f"transcribe:{SESSION}", ref="ears")
        await receive_until(comm, "audio_config")
        await Agent.respond(SESSION, "hello")
        await asyncio.sleep(0.05)
        assert Agent.running(SESSION)

        # The user starts talking again: the fake transcriber hears speech at once.
        await start(comm)
        await send_audio(comm, speech(1))
        await receive_until(comm, "clear", timeout=3, limit=500)

    assert not Agent.running(SESSION)


def test_sentences_are_released_as_they_complete() -> None:
    buffer = SentenceBuffer(min_chars=12)
    assert buffer.feed("Hello there. How ") == ["Hello there."]
    assert buffer.feed("are you? I'm fine") == ["How are you?"]
    assert buffer.flush() == "I'm fine"
    assert buffer.flush() is None


def test_tiny_sentences_wait_for_the_next() -> None:
    buffer = SentenceBuffer(min_chars=12)
    assert buffer.feed("Hi. ") == []
    assert buffer.feed("Ok. ") == []
    assert buffer.feed("That is all. ") == ["Hi. Ok. That is all."]


def test_line_breaks_end_sentences() -> None:
    buffer = SentenceBuffer(min_chars=5)
    assert buffer.feed("- first item\n- second item\n") == [
        "- first item",
        "- second item",
    ]


async def test_interrupting_a_new_run_keeps_the_previous_reply(app: Any) -> None:
    await Agent.respond(SESSION, "first")
    await asyncio.sleep(0.05)
    await Voice.wait_until_spoken(SESSION)

    Agent.gate = asyncio.Event()
    await Agent.respond(SESSION, "second")
    await asyncio.sleep(0.05)
    await Agent.interrupt(SESSION)

    turns = [(t.role, t.content) for t in await Agent.memory.load(SESSION)]
    assert turns[:3] == [
        ("user", "first"),
        ("assistant", "Sure, I can help with that today. Anything else?"),
        ("user", "second"),
    ]
