"""A transcriber that needs no provider: scripted words, paced by loud audio."""

import asyncio
import math
from array import array
from collections.abc import AsyncIterator
from typing import ClassVar

from ..audio_stream_in import (
    AudioStart,
    FinalFrame,
    PartialFrame,
    SpeechStartedFrame,
    TranscriberFrame,
    TranscriberTopic,
    UtteranceEndFrame,
)


def loudness(audio: bytes) -> float:
    """RMS of PCM16 audio, sampling every 4th sample: enough to tell speech from quiet."""
    samples = array("h", audio[: len(audio) - len(audio) % 2])
    if len(samples) == 0:
        return 0.0
    picked = samples[::4]
    return math.sqrt(sum(value * value for value in picked) / len(picked))


class FakeTranscriberStream:
    """Hears one scripted word per ``ms_per_word`` of loud audio; a pause ends the utterance."""

    def __init__(
        self,
        words: list[str],
        *,
        bytes_per_ms: float,
        ms_per_word: int,
        words_per_final: int,
        speech_level: float = 500,
        silence_ms: int = 600,
    ) -> None:
        self._words = words
        self._bytes_per_ms = bytes_per_ms
        self._ms_per_word = ms_per_word
        self._words_per_final = words_per_final
        self._speech_level = speech_level
        self._silence_ms = silence_ms
        self._frames: asyncio.Queue[TranscriberFrame | None] = asyncio.Queue()
        self._now = 0.0
        self._next = 0
        self._active = False
        self._loud_ms = 0.0
        self._quiet_ms = 0.0
        self._words_heard = 0
        self._segment: list[str] = []
        self._segment_start = 0
        self._ended = False

    async def send(self, audio: bytes) -> None:
        duration = len(audio) / self._bytes_per_ms
        loud = loudness(audio) >= self._speech_level
        if loud and not self._active:
            self._active = True
            self._loud_ms = self._quiet_ms = 0.0
            self._words_heard = 0
            self._segment_start = round(self._now)
            self._put(SpeechStartedFrame(at_ms=round(self._now)))
        self._now += duration
        if not self._active:
            return
        if loud:
            self._quiet_ms = 0.0
            self._loud_ms += duration
            while self._words_heard < int(self._loud_ms // self._ms_per_word):
                self._word()
        else:
            self._quiet_ms += duration
            if self._words_heard and self._quiet_ms >= self._silence_ms:
                self._end_utterance()

    async def keepalive(self) -> None:
        pass

    async def finish(self) -> None:
        if self._active and self._words_heard:
            self._end_utterance()
        self._stop()

    async def close(self) -> None:
        self._stop()

    async def frames(self) -> AsyncIterator[TranscriberFrame]:
        while (frame := await self._frames.get()) is not None:
            yield frame

    def _word(self) -> None:
        self._segment.append(self._words[self._next % len(self._words)])
        self._next += 1
        self._words_heard += 1
        if len(self._segment) >= self._words_per_final:
            self._final()
        else:
            self._put(
                PartialFrame(
                    text=" ".join(self._segment),
                    start_ms=self._segment_start,
                    end_ms=round(self._now),
                )
            )

    def _end_utterance(self) -> None:
        if self._segment:
            self._final()
        self._put(UtteranceEndFrame())
        self._active = False

    def _final(self) -> None:
        self._put(
            FinalFrame(
                text=" ".join(self._segment),
                start_ms=self._segment_start,
                end_ms=round(self._now),
                confidence=1.0,
            )
        )
        self._segment = []
        self._segment_start = round(self._now)

    def _put(self, frame: TranscriberFrame) -> None:
        if not self._ended:
            self._frames.put_nowait(frame)

    def _stop(self) -> None:
        if not self._ended:
            self._frames.put_nowait(None)
            self._ended = True


class FakeTranscriberTopic(TranscriberTopic):
    """Transcribes any audio as :attr:`script`, for demos, UI work and CI."""

    script: ClassVar[list[str]] = [
        "hello",
        "world",
        "this",
        "is",
        "a",
        "scripted",
        "transcript",
    ]
    ms_per_word: ClassVar[int] = 400
    words_per_final: ClassVar[int] = 4
    # Voice activity: speech RMS in PCM16 units, and the pause that ends an utterance.
    speech_level: ClassVar[float] = 500
    silence_ms: ClassVar[int] = 600

    # It costs nothing, so nothing is limited.
    max_session_seconds: ClassVar[float | None] = None
    idle_timeout_seconds: ClassVar[float | None] = None
    max_sessions_per_user: ClassVar[int | None] = None

    async def open_stream(self, audio: AudioStart) -> FakeTranscriberStream:
        bytes_per_ms = audio.sample_rate * audio.channels * 2 / 1000
        return FakeTranscriberStream(
            self.script,
            bytes_per_ms=bytes_per_ms,
            ms_per_word=self.ms_per_word,
            words_per_final=self.words_per_final,
            speech_level=self.speech_level,
            silence_ms=self.silence_ms,
        )
