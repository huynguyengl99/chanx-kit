"""Audio in, transcripts out: the transcriber@1 contract over chanx topics."""

import asyncio
import contextlib
import logging
import uuid
from typing import Any, ClassVar, Literal

from chanx.core.decorators import ws_handler
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage
from chanx.utils.scope import scope_user

from ..media_stream_in import ChunkSequencer, MediaIntake
from .messages import (
    AudioChunkMessage,
    AudioConfig,
    AudioConfigMessage,
    AudioEndMessage,
    AudioStart,
    AudioStartMessage,
    SpeechStarted,
    SpeechStartedMessage,
    TranscriberError,
    TranscriberErrorCode,
    TranscriberErrorMessage,
    Transcript,
    TranscriptFinal,
    TranscriptFinalMessage,
    TranscriptPartialMessage,
    UtteranceEnd,
    UtteranceEndMessage,
)
from .provider import (
    FinalFrame,
    PartialFrame,
    ProviderUnavailableError,
    SpeechStartedFrame,
    TranscriberFrame,
    TranscriberStream,
    UtteranceEndFrame,
)

logger = logging.getLogger(__name__)

TRANSCRIPT_EVENTS: list[type[BaseMessage]] = [
    SpeechStartedMessage,
    TranscriptPartialMessage,
    TranscriptFinalMessage,
    UtteranceEndMessage,
]


class AudioConfigRequestMessage(BaseMessage):
    """Client asks for the capture format again, without resubscribing."""

    action: Literal["audio_config_request"] = "audio_config_request"
    payload: None = None


class TranscriptTopic(
    Topic[
        SpeechStartedMessage
        | TranscriptPartialMessage
        | TranscriptFinalMessage
        | UtteranceEndMessage
    ]
):
    """Watch a session's transcripts read-only: ``transcript:<session>``."""

    pattern = "transcript:{session}"

    passthrough_events: ClassVar[list[type[BaseMessage]]] = TRANSCRIPT_EVENTS


class _Session:
    """One provider stream; holds chunks that arrive while it opens."""

    def __init__(self, sequencer: ChunkSequencer) -> None:
        self.stream: TranscriberStream | None = None
        self.sequencer = sequencer
        self.intake: MediaIntake | None = None
        self.held: list[bytes] = []
        self.end_requested = False
        self.tasks: list[asyncio.Task[None]] = []
        self.utterance_id: str | None = None
        self.closed = False

    def feed(self, chunk: bytes) -> None:
        if self.intake is None:
            self.held.append(chunk)
        else:
            self.intake.feed(chunk)


class TranscriberTopic(
    Topic[
        SpeechStartedMessage
        | TranscriptPartialMessage
        | TranscriptFinalMessage
        | UtteranceEndMessage
    ]
):
    """Audio in, transcripts out: ``transcribe:<session>``. Override ``open_stream``."""

    pattern = "transcribe:{session}"

    audio_config: ClassVar[AudioConfig] = AudioConfig()
    transcript_topic: ClassVar[type[TranscriptTopic]] = TranscriptTopic

    # Providers bill per second of audio, so every stream is bounded. None turns one off.
    max_session_seconds: ClassVar[float | None] = 300
    idle_timeout_seconds: ClassVar[float | None] = 15
    max_sessions_per_user: ClassVar[int | None] = 2
    keepalive_seconds: ClassVar[float | None] = 4
    finish_timeout_seconds: ClassVar[float] = 10

    queue_chunks: ClassVar[int] = 50
    reorder_window: ClassVar[int] = 8

    # Process-local, like the audio itself: a stream lives where its socket is.
    _open: ClassVar[dict[str, int]] = {}

    def __init__(self, consumer: Any, topic: str) -> None:
        super().__init__(consumer, topic)
        self._session: _Session | None = None
        self._counted: str | None = None

    @property
    def session_id(self) -> str:
        return self.params["session"]

    def current_user_id(self) -> str | None:
        """The user limits count against; None counts per connection."""
        user = scope_user(self.scope)
        if user is None:
            return None
        identifier = getattr(user, "pk", None) or getattr(user, "id", None)
        return None if identifier is None else str(identifier)

    def provider_available(self) -> bool:
        """False when the provider cannot work at all, e.g. no API key."""
        return True

    async def open_stream(self, audio: AudioStart) -> TranscriberStream:
        """Open a provider stream; raise ``ProviderUnavailableError`` if refused."""
        raise NotImplementedError(
            f"{type(self).__name__} must override open_stream() to connect a provider."
        )

    async def on_subscribe(self) -> None:
        await self.send_message(AudioConfigMessage(payload=self.audio_config))
        if not self.provider_available():
            await self.send_error(
                TranscriberErrorCode.PROVIDER_UNAVAILABLE,
                "The transcription provider is not configured.",
            )

    async def on_unsubscribe(self) -> None:
        await super().on_unsubscribe()
        await self.close_session()

    @ws_handler(
        summary="Ask for the capture format",
        description="Return the format to capture audio in, without resubscribing.",
    )
    async def handle_audio_config_request(
        self, _message: AudioConfigRequestMessage
    ) -> AudioConfigMessage:
        return AudioConfigMessage(payload=self.audio_config)

    @ws_handler(
        summary="Start streaming audio",
        description="Open a provider stream for audio in the negotiated format.",
        output_type=SpeechStartedMessage
        | TranscriptPartialMessage
        | TranscriptFinalMessage
        | UtteranceEndMessage
        | TranscriberErrorMessage,
    )
    async def handle_audio_start(self, message: AudioStartMessage) -> None:
        previous = self._session
        session = _Session(ChunkSequencer(window=self.reorder_window))
        self._session = session
        if previous is not None:
            await self._close(previous, graceful=False)

        refusal = self._refuse(message.payload)
        if refusal is not None:
            await self._abandon(session, *refusal)
            return
        if not self._claim():
            await self._abandon(
                session,
                TranscriberErrorCode.LIMIT_REACHED,
                f"At most {self.max_sessions_per_user} streams at once.",
            )
            return

        try:
            stream = await self.open_stream(message.payload)
        except Exception as error:  # noqa: BLE001 - any failure frees the session
            if not isinstance(error, ProviderUnavailableError):
                logger.exception("opening the transcriber stream failed")
            self._release()
            await self._abandon(
                session, TranscriberErrorCode.PROVIDER_UNAVAILABLE, str(error)
            )
            return
        if session.closed:  # replaced or left while the provider was connecting
            await stream.close()
            return

        session.stream = stream
        intake = MediaIntake(
            stream.send,
            on_end=stream.finish,
            on_quiet=lambda kind: self._on_quiet(session, kind),
            max_chunks=self.queue_chunks,
            keepalive_seconds=self.keepalive_seconds,
            idle_seconds=self.idle_timeout_seconds,
        )
        session.tasks.append(asyncio.ensure_future(self._listen(session)))
        session.intake = intake
        intake.start()
        for chunk in session.held:
            intake.feed(chunk)
        session.held.clear()
        if self.max_session_seconds is not None:
            session.tasks.append(
                asyncio.ensure_future(self._expire(session, self.max_session_seconds))
            )
        if session.end_requested:
            self._end(session)

    def _refuse(self, audio: AudioStart) -> tuple[TranscriberErrorCode, str] | None:
        expected = self.audio_config
        if (audio.encoding, audio.sample_rate, audio.channels) != (
            expected.encoding,
            expected.sample_rate,
            expected.channels,
        ):
            return (
                TranscriberErrorCode.BAD_FORMAT,
                f"Expected {expected.encoding} at {expected.sample_rate} Hz, "
                f"{expected.channels} channel(s).",
            )
        if not self.provider_available():
            return (
                TranscriberErrorCode.PROVIDER_UNAVAILABLE,
                "The transcription provider is not configured.",
            )
        return None

    async def _abandon(
        self, session: _Session, code: TranscriberErrorCode, text: str
    ) -> None:
        session.closed = True
        if self._session is session:
            self._session = None
        await self.send_error(code, text)

    @ws_handler(
        summary="Send audio",
        description="One chunk of the stream, numbered from 0 per audio_start.",
        output_type=TranscriberErrorMessage,
    )
    async def handle_audio_chunk(self, message: AudioChunkMessage) -> None:
        session = self._session
        if session is None or session.closed or session.end_requested:
            await self.send_error(
                TranscriberErrorCode.NOT_STARTED, "Send audio_start before audio."
            )
            return
        ready, gaps = session.sequencer.push(
            message.payload.index, message.payload.data
        )
        for chunk in ready:
            session.feed(chunk)
        for gap in gaps:
            await self.on_gap(gap.start, gap.end)

    @ws_handler(
        summary="End the audio",
        description="Flush the provider, deliver its last transcripts, then close.",
        output_type=TranscriberErrorMessage,
    )
    async def handle_audio_end(self, _message: AudioEndMessage) -> None:
        session = self._session
        if session is None or session.closed or session.end_requested:
            return
        session.end_requested = True
        ready, gaps = session.sequencer.flush()
        for chunk in ready:
            session.feed(chunk)
        if session.intake is not None:
            self._end(session)
        for gap in gaps:
            await self.on_gap(gap.start, gap.end)

    def _end(self, session: _Session) -> None:
        assert session.intake is not None
        session.intake.end()
        session.tasks.append(asyncio.ensure_future(self._finish_or_abort(session)))

    async def on_speech_started(self, event: SpeechStarted) -> None:
        await self.publish(SpeechStartedMessage(payload=event))

    async def on_partial(self, transcript: Transcript) -> None:
        await self.publish(TranscriptPartialMessage(payload=transcript))

    async def on_final(self, transcript: TranscriptFinal) -> None:
        """Override to act on finished text."""
        await self.publish(TranscriptFinalMessage(payload=transcript))

    async def on_utterance_end(self, event: UtteranceEnd) -> None:
        await self.publish(UtteranceEndMessage(payload=event))

    async def on_gap(self, start: int, end: int) -> None:
        """Report lost chunks rather than feed the provider made-up silence."""
        await self.send_error(
            TranscriberErrorCode.AUDIO_GAP, f"Chunks {start} to {end - 1} were lost."
        )

    async def publish(self, message: BaseMessage) -> None:
        """Send to this connection and to the session's transcript watchers."""
        await self.safe_send(message)
        await self.transcript_topic.broadcast(f"transcript:{self.session_id}", message)

    async def send_error(self, code: TranscriberErrorCode, text: str) -> None:
        await self.safe_send(
            TranscriberErrorMessage(payload=TranscriberError(code=code, message=text))
        )

    async def safe_send(self, message: BaseMessage) -> None:
        # Frames arrive from background tasks, which can outlive the socket.
        try:
            await self.send_message(message)
        except Exception:  # noqa: BLE001 - a closed socket must not kill the stream task
            logger.debug("could not send %s; the connection is gone", message.action)

    def _identity(self) -> str:
        return self.current_user_id() or f"connection:{self.channel_name}"

    def _claim(self) -> bool:
        identity = self._identity()
        if (
            self.max_sessions_per_user is not None
            and self._open.get(identity, 0) >= self.max_sessions_per_user
        ):
            return False
        self._open[identity] = self._open.get(identity, 0) + 1
        self._counted = identity
        return True

    def _release(self) -> None:
        identity, self._counted = self._counted, None
        if identity is None:
            return
        remaining = self._open.get(identity, 0) - 1
        if remaining > 0:
            self._open[identity] = remaining
        else:
            self._open.pop(identity, None)

    async def close_session(self) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        await self._close(session, graceful=False)

    async def _close(self, session: _Session, *, graceful: bool) -> None:
        if session.closed:
            return
        session.closed = True
        current = asyncio.current_task()
        if session.intake is not None and session.intake.running:
            await session.intake.stop()
        if not graceful and session.stream is not None:
            with contextlib.suppress(Exception):
                await session.stream.close()
        for task in session.tasks:
            if task is not current and not task.done():
                task.cancel()
        if self._session is session:
            self._session = None
        self._release()

    async def _on_quiet(self, session: _Session, kind: str) -> None:
        if kind == "keepalive":
            assert session.stream is not None
            await session.stream.keepalive()
            return
        await self.send_error(
            TranscriberErrorCode.LIMIT_REACHED, "No audio arrived for too long."
        )
        await self._close(session, graceful=False)

    async def _expire(self, session: _Session, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if session.closed:
            return
        await self.send_error(
            TranscriberErrorCode.LIMIT_REACHED,
            f"Streams are limited to {seconds:g} seconds.",
        )
        await self._close(session, graceful=False)

    async def _finish_or_abort(self, session: _Session) -> None:
        listener = session.tasks[0]
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(
                asyncio.shield(listener), self.finish_timeout_seconds
            )
        await self._close(session, graceful=listener.done())

    async def _listen(self, session: _Session) -> None:
        assert session.stream is not None
        try:
            async for frame in session.stream.frames():
                if session.closed:
                    break
                await self._on_frame(session, frame)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - reported to the client
            logger.exception("transcriber stream failed")
            await self.send_error(TranscriberErrorCode.PROVIDER_UNAVAILABLE, str(error))
            await self._close(session, graceful=False)
            return
        # The provider closed the stream: after audio_end, or on its own.
        if session.utterance_id is not None:
            await self.on_utterance_end(UtteranceEnd(utterance_id=session.utterance_id))
            session.utterance_id = None
        await self._close(session, graceful=True)

    async def _on_frame(self, session: _Session, frame: TranscriberFrame) -> None:
        match frame:
            case SpeechStartedFrame(at_ms=at_ms):
                await self.on_speech_started(SpeechStarted(at_ms=at_ms))
            case PartialFrame():
                await self.on_partial(
                    Transcript(
                        utterance_id=self._utterance(session),
                        text=frame.text,
                        start_ms=frame.start_ms,
                        end_ms=frame.end_ms,
                    )
                )
            case FinalFrame():
                await self.on_final(
                    TranscriptFinal(
                        utterance_id=self._utterance(session),
                        text=frame.text,
                        start_ms=frame.start_ms,
                        end_ms=frame.end_ms,
                        confidence=frame.confidence,
                    )
                )
            case UtteranceEndFrame():
                if session.utterance_id is not None:
                    utterance_id, session.utterance_id = session.utterance_id, None
                    await self.on_utterance_end(UtteranceEnd(utterance_id=utterance_id))

    def _utterance(self, session: _Session) -> str:
        if session.utterance_id is None:
            session.utterance_id = uuid.uuid4().hex
        return session.utterance_id
