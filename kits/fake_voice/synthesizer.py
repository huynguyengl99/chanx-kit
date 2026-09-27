"""A synthesizer that needs no provider: a short tone per word."""

import asyncio
import math
import struct
import zlib
from collections.abc import AsyncIterator
from typing import ClassVar

from ..audio_stream_out import SpeechFormat, SynthesizerTopic


def word_tones(
    text: str, audio: SpeechFormat, word_ms: int, gap_ms: int
) -> list[bytes]:
    """One tone per word, pitched by the word, then a gap: speech-like pacing."""
    rate = audio.sample_rate
    pieces: list[bytes] = []
    for word in text.split():
        pitch = 180 + zlib.crc32(word.lower().encode()) % 220
        tone = rate * word_ms // 1000
        fade = max(1, tone // 10)
        samples: list[int] = []
        for i in range(tone):
            envelope = min(1.0, i / fade, (tone - i) / fade)
            value = int(6000 * envelope * math.sin(2 * math.pi * pitch * i / rate))
            samples.extend([value] * audio.channels)
        samples.extend([0] * (rate * gap_ms // 1000) * audio.channels)
        pieces.append(struct.pack(f"<{len(samples)}h", *samples))
    return pieces


class FakeSynthesizerTopic(SynthesizerTopic):
    """Speaks any text as a tone per word, for demos, UI work and CI."""

    word_ms: ClassVar[int] = 180
    gap_ms: ClassVar[int] = 70
    # 1.0 streams in real time; 0 sends at once.
    pace: ClassVar[float] = 1.0

    @classmethod
    async def synthesize(
        cls, text: str, voice: str | None, audio: SpeechFormat
    ) -> AsyncIterator[bytes]:
        for piece in word_tones(text, audio, cls.word_ms, cls.gap_ms):
            yield piece
            if cls.pace:
                await asyncio.sleep((cls.word_ms + cls.gap_ms) / 1000 * cls.pace)
