"""The synthesizer@1 contract: text in, audio out."""

from enum import StrEnum
from typing import Literal

from chanx.messages.base import BaseMessage
from pydantic import BaseModel, Field

from ..media_stream_in import Base64Data


class SpeechFormat(BaseModel):
    """Raw audio: PCM16 little-endian, interleaved when there are several channels."""

    encoding: Literal["pcm16"] = "pcm16"
    sample_rate: int = Field(default=24000, gt=0)
    channels: int = Field(default=1, gt=0)


class Speak(BaseModel):
    text: str
    voice: str | None = None
    utterance_id: str | None = None


class SpeakMessage(BaseMessage):
    """Client asks for text to be spoken. Queued behind what is already speaking."""

    action: Literal["speak"] = "speak"
    payload: Speak


class SpeakClearMessage(BaseMessage):
    """Client asks to stop: the utterance playing and everything queued."""

    action: Literal["speak_clear"] = "speak_clear"
    payload: None = None


class PlaybackMark(BaseModel):
    """How much of an utterance was actually heard, in milliseconds."""

    utterance_id: str
    played_ms: int = Field(ge=0)


class PlaybackMarkMessage(BaseMessage):
    """Client reports playback progress, so the server knows what was heard."""

    action: Literal["playback_mark"] = "playback_mark"
    payload: PlaybackMark


class SpeechAudioStart(SpeechFormat):
    utterance_id: str
    text: str


class SpeechAudioStartMessage(BaseMessage):
    """An utterance begins, in this format."""

    action: Literal["audio_start"] = "audio_start"
    payload: SpeechAudioStart


class SpeechAudioChunk(BaseModel):
    """``index`` counts from 0 per utterance, so a replayed chunk can be recognised."""

    utterance_id: str
    index: int = Field(ge=0)
    data: Base64Data


class SpeechAudioChunkMessage(BaseMessage):
    """A piece of the utterance's audio."""

    action: Literal["audio_chunk"] = "audio_chunk"
    payload: SpeechAudioChunk


class SpeechAudioEnd(BaseModel):
    utterance_id: str
    duration_ms: int


class SpeechAudioEndMessage(BaseMessage):
    """The utterance's audio is complete."""

    action: Literal["audio_end"] = "audio_end"
    payload: SpeechAudioEnd


class SpeechClear(BaseModel):
    """The utterance that was playing, if any."""

    utterance_id: str | None = None


class SpeechClearMessage(BaseMessage):
    """Stop playing now and drop anything buffered: an interruption."""

    action: Literal["clear"] = "clear"
    payload: SpeechClear


class SynthesizerErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    BAD_REQUEST = "bad_request"
    PROVIDER_FAILED = "provider_failed"


class SynthesizerError(BaseModel):
    code: SynthesizerErrorCode
    message: str
    utterance_id: str | None = None


class SynthesizerErrorMessage(BaseMessage):
    """An utterance could not be spoken."""

    action: Literal["synthesizer_error"] = "synthesizer_error"
    payload: SynthesizerError
