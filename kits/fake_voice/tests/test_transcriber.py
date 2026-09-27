import struct
from typing import ClassVar

import pytest

from ...audio_stream_in import TranscriberTopic
from ...audio_stream_in.tests.contract import TranscriberContract
from ..transcriber import FakeTranscriberStream, FakeTranscriberTopic


class HelloWorld(FakeTranscriberTopic):
    # The contract suite sends one second of audio and expects "hello world".
    script: ClassVar[list[str]] = ["hello", "world"]
    ms_per_word = 500
    words_per_final = 2


class TestFakeTranscriberMeetsTheContract(TranscriberContract):
    @pytest.fixture
    def transcriber_topic(self) -> type[TranscriberTopic]:
        return HelloWorld


def tone(ms: int, bytes_per_ms: int = 48) -> bytes:
    """Loud enough to count as speech."""
    return struct.pack("<h", 4000) * (ms * bytes_per_ms // 2)


def quiet(ms: int, bytes_per_ms: int = 48) -> bytes:
    return bytes(ms * bytes_per_ms)


def stream(words: list[str], words_per_final: int = 10) -> FakeTranscriberStream:
    return FakeTranscriberStream(
        words,
        bytes_per_ms=48,
        ms_per_word=100,
        words_per_final=words_per_final,
        silence_ms=300,
    )


async def frames_for(stream: FakeTranscriberStream, *chunks: bytes) -> list[object]:
    for chunk in chunks:
        await stream.send(chunk)
    await stream.finish()
    return [frame async for frame in stream.frames()]


def described(frames: list[object]) -> list[tuple[str, str | None]]:
    return [(type(f).__name__, getattr(f, "text", None)) for f in frames]


async def test_words_are_paced_by_loud_audio() -> None:
    frames = await frames_for(stream(["a", "b", "c"]), tone(250))

    assert described(frames) == [
        ("SpeechStartedFrame", None),
        ("PartialFrame", "a"),
        ("PartialFrame", "a b"),
        ("FinalFrame", "a b"),
        ("UtteranceEndFrame", None),
    ]


async def test_long_speech_is_split_into_finals_and_the_script_repeats() -> None:
    frames = await frames_for(stream(["a", "b"], words_per_final=2), tone(500))

    finals = [text for name, text in described(frames) if name == "FinalFrame"]
    assert finals == ["a b", "a b", "a"]


async def test_a_pause_ends_the_utterance_and_speech_starts_another() -> None:
    frames = await frames_for(
        stream(["one", "two", "three", "four"]),
        *[tone(100)] * 2,
        *[quiet(100)] * 4,
        *[tone(100)] * 2,
    )

    assert described(frames) == [
        ("SpeechStartedFrame", None),
        ("PartialFrame", "one"),
        ("PartialFrame", "one two"),
        ("FinalFrame", "one two"),
        ("UtteranceEndFrame", None),
        ("SpeechStartedFrame", None),
        ("PartialFrame", "three"),
        ("PartialFrame", "three four"),
        ("FinalFrame", "three four"),
        ("UtteranceEndFrame", None),
    ]


async def test_a_short_pause_does_not_end_the_utterance() -> None:
    frames = await frames_for(stream(["a", "b", "c"]), tone(100), quiet(200), tone(100))
    assert [name for name, _ in described(frames)].count("UtteranceEndFrame") == 1


async def test_silence_alone_produces_nothing() -> None:
    assert await frames_for(stream(["a"]), quiet(1000)) == []
