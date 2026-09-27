"""Text in, audio out: the synthesizer@1 contract over a chanx topic."""

import logging
import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

from chanx.core.decorators import ws_handler
from chanx.core.envelope import current_seq
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage

from ..media_stream_out import InMemoryReplayStore, ReplayStore, SerialJobs
from .messages import (
    PlaybackMarkMessage,
    SpeakClearMessage,
    SpeakMessage,
    SpeechAudioChunk,
    SpeechAudioChunkMessage,
    SpeechAudioEnd,
    SpeechAudioEndMessage,
    SpeechAudioStart,
    SpeechAudioStartMessage,
    SpeechClear,
    SpeechClearMessage,
    SpeechFormat,
    SynthesizerError,
    SynthesizerErrorCode,
    SynthesizerErrorMessage,
)
from .playback import InMemoryPlaybackStore, PlaybackStore

logger = logging.getLogger(__name__)

SPEECH_EVENTS: list[type[BaseMessage]] = [
    SpeechAudioStartMessage,
    SpeechAudioChunkMessage,
    SpeechAudioEndMessage,
    SpeechClearMessage,
    SynthesizerErrorMessage,
]
_BY_ACTION: dict[str, type[BaseMessage]] = {
    message.model_fields["action"].default: message for message in SPEECH_EVENTS
}


class SynthesizerUnavailableError(Exception):
    """The provider cannot be used: no credentials, or it refused the request."""


class SynthesizerTopic(
    Topic[
        SpeechAudioStartMessage
        | SpeechAudioChunkMessage
        | SpeechAudioEndMessage
        | SpeechClearMessage
        | SynthesizerErrorMessage
    ]
):
    """Text to speech for everyone on ``speak:<session>``. Override ``synthesize``."""

    pattern = "speak:{session}"

    passthrough_events: ClassVar[list[type[BaseMessage]]] = SPEECH_EVENTS

    output_format: ClassVar[SpeechFormat] = SpeechFormat()
    default_voice: ClassVar[str | None] = None
    # Refused rather than billed.
    max_text_chars: ClassVar[int] = 2000
    max_chunk_ms: ClassVar[int] = 200

    replay_store: ClassVar[ReplayStore] = InMemoryReplayStore()
    playback_store: ClassVar[PlaybackStore] = InMemoryPlaybackStore()
    _jobs: ClassVar[SerialJobs] = SerialJobs()

    @property
    def session_id(self) -> str:
        return self.params["session"]

    @classmethod
    def provider_available(cls) -> bool:
        """False when the provider cannot work at all, such as a missing API key."""
        return True

    @classmethod
    async def synthesize(
        cls, text: str, voice: str | None, audio: SpeechFormat
    ) -> AsyncIterator[bytes]:
        """Yield PCM16 audio for ``text``; raise ``SynthesizerUnavailableError`` if refused."""
        raise NotImplementedError(
            f"{cls.__name__} must override synthesize() to connect a provider."
        )
        yield b""  # pragma: no cover - marks this as an async generator

    @classmethod
    def topic_for(cls, session: str) -> str:
        return f"speak:{session}"

    @classmethod
    def _key(cls, session: str) -> str:
        # Per class, so two synthesizer topics on one session stay separate.
        return f"{cls.__name__}:{session}"

    @classmethod
    async def speak(
        cls,
        session: str,
        text: str,
        *,
        voice: str | None = None,
        utterance_id: str | None = None,
    ) -> str:
        """Queue ``text`` on ``session`` (utterances play in order); return its id."""
        utterance = utterance_id or uuid.uuid4().hex
        text = text.strip()
        if not text:
            await cls._emit_error(
                session, SynthesizerErrorCode.BAD_REQUEST, "Nothing to say.", utterance
            )
            return utterance
        if len(text) > cls.max_text_chars:
            await cls._emit_error(
                session,
                SynthesizerErrorCode.BAD_REQUEST,
                f"Text is limited to {cls.max_text_chars} characters.",
                utterance,
            )
            return utterance

        async def job() -> None:
            await cls._produce(session, utterance, text, voice or cls.default_voice)

        cls._jobs.submit(cls._key(session), job)
        return utterance

    @classmethod
    async def clear(cls, session: str) -> None:
        """Stop speaking on ``session`` now: the utterance playing and all queued."""
        current = await cls._current(session)
        await cls._jobs.cancel(cls._key(session))
        await cls.replay_store.clear(cls._key(session))
        await cls.broadcast(
            cls.topic_for(session),
            SpeechClearMessage(payload=SpeechClear(utterance_id=current)),
        )

    @classmethod
    def is_speaking(cls, session: str) -> bool:
        """Whether something is playing or queued on this process."""
        return cls._jobs.busy(cls._key(session))

    @classmethod
    async def wait_until_spoken(cls, session: str) -> None:
        """Until everything queued on this process has been sent. Mostly for tests."""
        await cls._jobs.wait(cls._key(session))

    async def on_subscribe(self) -> None:
        """Replay the utterance in flight: audio cannot be joined part-way."""
        for seq, message in await self.replay_store.replay(self._key(self.session_id)):
            token = current_seq.set(seq)
            try:
                await self.send_message(
                    _BY_ACTION[message["action"]].model_validate(message)
                )
            finally:
                current_seq.reset(token)

    @ws_handler(
        summary="Speak text",
        description="Queue text to be spoken to everyone on the session.",
        output_type=SpeechAudioStartMessage
        | SpeechAudioChunkMessage
        | SpeechAudioEndMessage
        | SynthesizerErrorMessage,
    )
    async def handle_speak(self, message: SpeakMessage) -> None:
        if not self.provider_available():
            await self.send_message(
                SynthesizerErrorMessage(
                    payload=SynthesizerError(
                        code=SynthesizerErrorCode.PROVIDER_UNAVAILABLE,
                        message="The speech provider is not configured.",
                        utterance_id=message.payload.utterance_id,
                    )
                )
            )
            return
        await type(self).speak(
            self.session_id,
            message.payload.text,
            voice=message.payload.voice,
            utterance_id=message.payload.utterance_id,
        )

    @ws_handler(
        summary="Stop speaking",
        description="Stop the utterance playing and drop everything queued.",
        output_type=SpeechClearMessage,
    )
    async def handle_speak_clear(self, _message: SpeakClearMessage) -> None:
        await type(self).clear(self.session_id)

    @ws_handler(
        summary="Report playback",
        description="How much of an utterance the client has actually played.",
    )
    async def handle_playback_mark(self, message: PlaybackMarkMessage) -> None:
        mark = message.payload
        await self.playback_store.mark(
            self.session_id, mark.utterance_id, mark.played_ms
        )
        await self.on_playback_mark(mark.utterance_id, mark.played_ms)

    async def on_playback_mark(self, utterance_id: str, played_ms: int) -> None:
        """Override to react to playback progress. The store is already updated."""

    @classmethod
    async def _current(cls, session: str) -> str | None:
        """The utterance being sent, from the replay buffer."""
        buffered = await cls.replay_store.replay(cls._key(session))
        return buffered[-1][1]["payload"].get("utterance_id") if buffered else None

    @classmethod
    async def _emit(
        cls, session: str, message: BaseMessage, *, record: bool = True
    ) -> None:
        seq = None
        if record:
            seq = await cls.replay_store.append(
                cls._key(session), message.model_dump(mode="json")
            )
        await cls.broadcast(cls.topic_for(session), message, seq=seq)

    @classmethod
    async def _emit_error(
        cls, session: str, code: SynthesizerErrorCode, text: str, utterance: str | None
    ) -> None:
        await cls._emit(
            session,
            SynthesizerErrorMessage(
                payload=SynthesizerError(
                    code=code, message=text, utterance_id=utterance
                )
            ),
            record=False,
        )

    @classmethod
    async def _produce(
        cls, session: str, utterance: str, text: str, voice: str | None
    ) -> None:
        key = cls._key(session)
        audio = cls.output_format
        frame_bytes = audio.channels * 2
        max_bytes = max(
            frame_bytes,
            audio.sample_rate * cls.max_chunk_ms // 1000 * frame_bytes,
        )

        await cls.replay_store.clear(key)
        await cls.playback_store.spoken(session, utterance, text)
        await cls._emit(
            session,
            SpeechAudioStartMessage(
                payload=SpeechAudioStart(
                    utterance_id=utterance, text=text, **audio.model_dump()
                )
            ),
        )

        index = 0
        total = 0
        held = b""  # a provider chunk can end mid-sample
        try:
            async for piece in cls.synthesize(text, voice, audio):
                held += piece
                usable = len(held) - len(held) % frame_bytes
                for start in range(0, usable, max_bytes):
                    data = held[start : min(start + max_bytes, usable)]
                    await cls._emit(
                        session,
                        SpeechAudioChunkMessage(
                            payload=SpeechAudioChunk(
                                utterance_id=utterance, index=index, data=data
                            )
                        ),
                    )
                    index += 1
                    total += len(data)
                held = held[usable:]
        except SynthesizerUnavailableError as error:
            await cls._emit_error(
                session,
                SynthesizerErrorCode.PROVIDER_UNAVAILABLE,
                str(error),
                utterance,
            )
        except Exception as error:  # noqa: BLE001 - reported to every listener
            logger.exception("synthesis failed")
            await cls._emit_error(
                session, SynthesizerErrorCode.PROVIDER_FAILED, str(error), utterance
            )

        duration_ms = total * 1000 // (audio.sample_rate * frame_bytes)
        await cls.playback_store.finished(session, utterance, duration_ms)
        await cls._emit(
            session,
            SpeechAudioEndMessage(
                payload=SpeechAudioEnd(utterance_id=utterance, duration_ms=duration_ms)
            ),
        )
        await cls.replay_store.clear(key)
