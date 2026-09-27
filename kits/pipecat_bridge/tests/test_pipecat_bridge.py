"""Run with Pipecat installed (``uv pip install pipecat-ai``); skipped without it."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import (  # noqa: E402
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessor  # noqa: E402
from pipecat.services.stt_service import STTService  # noqa: E402

from ...audio_stream_in import AudioStart, TranscriberTopic  # noqa: E402
from ...audio_stream_in.tests.contract import TranscriberContract  # noqa: E402
from ..topics import PipecatTranscriberTopic  # noqa: E402


class ScriptedSTT(STTService):
    """A Pipecat STT service hearing "hello", then "hello world"."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bytes = 0
        self._said = False

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        self._bytes += len(audio)
        if not self._said and self._bytes >= 9600:
            self._said = True
            yield InterimTranscriptionFrame("hello", "user", "t")
            yield TranscriptionFrame("hello world", "user", "t")
        yield None


class ScriptedPipecat(PipecatTranscriberTopic):
    def processors(self, audio: AudioStart) -> list[FrameProcessor]:
        return [ScriptedSTT()]


class TestPipecatBridgeMeetsTheContract(TranscriberContract):
    @pytest.fixture
    def transcriber_topic(self) -> type[TranscriberTopic]:
        return ScriptedPipecat


async def sink_output(*frames: Frame) -> list[str]:
    import asyncio

    from pipecat.processors.frame_processor import FrameDirection

    from ..topics import TranscriberSink

    class Last(TranscriberSink):
        """The sink with nothing after it, outside a running pipeline."""

        async def push_frame(self, frame: Frame, direction: Any = None) -> None:
            pass

    out: asyncio.Queue[Any] = asyncio.Queue()
    sink = Last(out, 24000)
    for frame in frames:
        await sink.process_frame(frame, FrameDirection.DOWNSTREAM)
    names: list[str] = []
    while not out.empty():
        names.append(type(out.get_nowait()).__name__)
    return names


async def test_voice_activity_ends_the_utterance_after_its_final() -> None:
    from pipecat.frames.frames import (
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )

    # VAD notices the pause before the service finalizes; the end waits for the final.
    assert await sink_output(
        VADUserStartedSpeakingFrame(),
        InterimTranscriptionFrame("hel", "user", "t"),
        VADUserStoppedSpeakingFrame(),
        TranscriptionFrame("hello", "user", "t"),
    ) == ["SpeechStartedFrame", "PartialFrame", "FinalFrame", "UtteranceEndFrame"]


async def test_a_pause_with_nothing_heard_still_ends_before_the_next_speech() -> None:
    from pipecat.frames.frames import (
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )

    assert await sink_output(
        VADUserStartedSpeakingFrame(),
        VADUserStoppedSpeakingFrame(),
        VADUserStartedSpeakingFrame(),
    ) == ["SpeechStartedFrame", "UtteranceEndFrame", "SpeechStartedFrame"]
