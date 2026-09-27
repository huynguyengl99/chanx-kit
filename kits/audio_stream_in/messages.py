"""The transcriber@1 contract: audio in, transcripts out."""

from enum import StrEnum
from typing import Literal

from chanx.messages.base import BaseMessage
from pydantic import BaseModel, Field

from ..media_stream_in import Base64Data


class AudioFormat(BaseModel):
    """Raw audio: PCM16 little-endian, interleaved when there are several channels."""

    encoding: Literal["pcm16"] = "pcm16"
    sample_rate: int = Field(default=24000, gt=0)
    channels: int = Field(default=1, gt=0)


class AudioConfig(AudioFormat):
    """The format the server wants, and how much audio to put in each chunk."""

    chunk_ms: int = Field(default=100, gt=0)


class AudioConfigMessage(BaseMessage):
    """Sent on subscribe: capture to this format."""

    action: Literal["audio_config"] = "audio_config"
    payload: AudioConfig


class AudioStart(AudioFormat):
    """The format actually captured, which must match ``audio_config``."""

    language: str | None = None


class AudioStartMessage(BaseMessage):
    """Client begins a stream of audio."""

    action: Literal["audio_start"] = "audio_start"
    payload: AudioStart


class AudioChunk(BaseModel):
    """``index`` counts from 0 for each ``audio_start``, so a gap can be detected."""

    index: int = Field(ge=0)
    data: Base64Data


class AudioChunkMessage(BaseMessage):
    """A piece of the stream."""

    action: Literal["audio_chunk"] = "audio_chunk"
    payload: AudioChunk


class AudioEndMessage(BaseMessage):
    """The stream is over: flush what the provider holds, then close it."""

    action: Literal["audio_end"] = "audio_end"
    payload: None = None


class SpeechStarted(BaseModel):
    at_ms: int


class SpeechStartedMessage(BaseMessage):
    """The provider heard speech begin, for barge-in and "listening" indicators."""

    action: Literal["speech_started"] = "speech_started"
    payload: SpeechStarted


class Transcript(BaseModel):
    """Times are milliseconds from the ``audio_start`` of this stream."""

    utterance_id: str
    text: str
    start_ms: int
    end_ms: int


class TranscriptPartialMessage(BaseMessage):
    """The segment being spoken, so far. Replaces the previous partial of the utterance."""

    action: Literal["transcript_partial"] = "transcript_partial"
    payload: Transcript


class TranscriptFinal(Transcript):
    confidence: float | None = None


class TranscriptFinalMessage(BaseMessage):
    """A segment that will not change. An utterance is its finals in order."""

    action: Literal["transcript_final"] = "transcript_final"
    payload: TranscriptFinal


class UtteranceEnd(BaseModel):
    utterance_id: str


class UtteranceEndMessage(BaseMessage):
    """The speaker paused: the utterance is complete."""

    action: Literal["utterance_end"] = "utterance_end"
    payload: UtteranceEnd


class TranscriberErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    LIMIT_REACHED = "limit_reached"
    BAD_FORMAT = "bad_format"
    AUDIO_GAP = "audio_gap"
    NOT_STARTED = "not_started"


class TranscriberError(BaseModel):
    code: TranscriberErrorCode
    message: str


class TranscriberErrorMessage(BaseMessage):
    """Something went wrong. Every code except ``audio_gap`` ends the stream."""

    action: Literal["transcriber_error"] = "transcriber_error"
    payload: TranscriberError


TranscriptEvent = (
    SpeechStartedMessage
    | TranscriptPartialMessage
    | TranscriptFinalMessage
    | UtteranceEndMessage
)
