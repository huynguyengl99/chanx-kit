"""A voice agent: audio in, transcriber, an AG-UI agent, synthesizer, audio out."""

import uuid
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from ag_ui.core import (
    AssistantMessage,
    CustomEvent,
    Event,
    RunAgentInput,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    UserMessage,
)

from ..ag_ui import AgUiTopic, ThreadBusyError
from ..audio_stream_in import (
    SpeechStarted,
    TranscriberTopic,
    TranscriptFinal,
    UtteranceEnd,
)
from ..audio_stream_out import SynthesizerTopic, heard_text
from .memory import InMemoryVoiceMemory, Turn, VoiceMemory
from .sentences import SentenceBuffer


class VoiceAgentTopic(AgUiTopic):
    """An AG-UI topic that speaks each reply sentence on ``synthesizer`` as it completes."""

    broadcast_run_events: ClassVar[bool] = True

    synthesizer: ClassVar[type[SynthesizerTopic]]
    memory: ClassVar[VoiceMemory] = InMemoryVoiceMemory()
    # Off for a provider that keeps its own history (pydantic-ai-ag-ui).
    send_history: ClassVar[bool] = True
    min_sentence_chars: ClassVar[int] = 12
    # Speaking rate, to trim a reply cut off before its audio was complete.
    ms_per_char: ClassVar[int] = 65

    # Per session, this process only.
    _spoken: ClassVar[dict[str, list[tuple[str, str]]]] = {}
    _reply: ClassVar[dict[str, str]] = {}

    async def run_events(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        session = self.thread_id
        buffer = SentenceBuffer(self.min_sentence_chars)
        spoken = self._spoken[session] = []
        self._reply.pop(session, None)
        reply: list[str] = []
        reply_id = uuid.uuid4().hex

        async def say(text: str) -> None:
            utterance = await self.synthesizer.speak(session, text)
            spoken.append((utterance, text))

        async for event in super().run_events(run_input):
            yield event
            match event:
                case TextMessageStartEvent(message_id=message_id):
                    reply_id = message_id
                case TextMessageContentEvent(delta=delta):
                    reply.append(delta)
                    for sentence in buffer.feed(delta):
                        await say(sentence)
                case TextMessageEndEvent():
                    if rest := buffer.flush():
                        await say(rest)
                case _:
                    pass

        # Reached only when the run was not interrupted; interrupt() keeps what was heard.
        if text := "".join(reply).strip():
            await self._remember(session, AssistantMessage(id=reply_id, content=text))
            self._reply[session] = reply_id

    @classmethod
    async def respond(cls, session: str, text: str) -> str | None:
        """Run the agent on the conversation plus ``text``; None if the thread is busy."""
        user = UserMessage(id=uuid.uuid4().hex, content=text)
        turns = await cls._remember(session, user)
        run_input = RunAgentInput(
            thread_id=session,
            run_id=uuid.uuid4().hex,
            state={},
            messages=list(turns) if cls.send_history else [user],
            tools=[],
            context=[],
            forwarded_props={},
        )
        try:
            return await cls.start_run(session, run_input)
        except ThreadBusyError:
            return None

    @classmethod
    async def interrupt(cls, session: str) -> str | None:
        """Barge-in: stop speech and the run, keep what was heard; None if quiet."""
        spoken = cls._spoken.pop(session, [])
        if not (cls.running(session) or cls.synthesizer.is_speaking(session)):
            return None
        await cls.synthesizer.clear(session)
        cls.cancel_run(session)

        heard = await cls._heard(session, spoken)
        turns = await cls.memory.load(session)
        reply_id = cls._reply.pop(session, None)
        # A finished reply was remembered whole; keep only what was heard.
        turns = [turn for turn in turns if turn.id != reply_id]
        if heard:
            turns.append(
                AssistantMessage(id=reply_id or uuid.uuid4().hex, content=heard)
            )
        await cls.memory.save(session, turns)
        await cls.emit_to_thread(
            session, CustomEvent(name="voice_interrupted", value={"heard": heard})
        )
        return heard

    @classmethod
    async def _heard(cls, session: str, spoken: list[tuple[str, str]]) -> str:
        parts: list[str] = []
        for utterance_id, text in spoken:
            utterance = await cls.synthesizer.playback_store.get(session, utterance_id)
            if utterance is None or utterance.played_ms <= 0:
                break
            duration = (
                utterance.duration_ms
                if utterance.finished
                else len(text) * cls.ms_per_char
            )
            if utterance.played_ms >= duration:
                parts.append(text)
                continue
            if part := heard_text(text, duration, utterance.played_ms):
                parts.append(part)
            break
        return " ".join(parts)

    @classmethod
    async def _remember(cls, session: str, turn: Turn) -> list[Turn]:
        turns = [*await cls.memory.load(session), turn]
        await cls.memory.save(session, turns)
        return turns


class VoiceTranscriberTopic(TranscriberTopic):
    """Utterances become agent runs; speech over the agent interrupts it."""

    agent_topic: ClassVar[type[VoiceAgentTopic]]
    interrupt_on_speech: ClassVar[bool] = True

    def __init__(self, consumer: Any, topic: str) -> None:
        super().__init__(consumer, topic)
        self._finals: list[str] = []

    async def on_speech_started(self, event: SpeechStarted) -> None:
        await super().on_speech_started(event)
        if self.interrupt_on_speech:
            await self.agent_topic.interrupt(self.session_id)

    async def on_final(self, transcript: TranscriptFinal) -> None:
        await super().on_final(transcript)
        self._finals.append(transcript.text)

    async def on_utterance_end(self, event: UtteranceEnd) -> None:
        await super().on_utterance_end(event)
        text, self._finals = " ".join(self._finals).strip(), []
        if text:
            await self.on_turn(text)

    async def on_turn(self, text: str) -> None:
        """The user finished saying ``text``. Override to filter or route it."""
        await self.agent_topic.respond(self.session_id, text)
