"""A Pipecat pipeline behind a chanx transcriber topic; chanx keeps the socket."""

import asyncio
from collections.abc import AsyncIterator

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

from ..audio_stream_in import (
    AudioStart,
    FinalFrame,
    PartialFrame,
    SpeechStartedFrame,
    TranscriberFrame,
    TranscriberTopic,
    UtteranceEndFrame,
)


class TranscriberSink(FrameProcessor):
    """Pipecat frames to transcriber frames; an utterance end waits for its final."""

    def __init__(
        self, out: "asyncio.Queue[TranscriberFrame | None]", rate: int
    ) -> None:
        super().__init__()
        self._out = out
        self._rate = rate
        self.heard_bytes = 0
        self._end_pending = False

    def _now(self) -> int:
        return self.heard_bytes * 1000 // (self._rate * 2)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        now = self._now()
        match frame:
            case InterimTranscriptionFrame(text=text) if text.strip():
                self._out.put_nowait(
                    PartialFrame(text=text.strip(), start_ms=0, end_ms=now)
                )
            case TranscriptionFrame(text=text) if text.strip():
                self._out.put_nowait(
                    FinalFrame(text=text.strip(), start_ms=0, end_ms=now)
                )
                self._end_if_pending()
            case UserStartedSpeakingFrame() | VADUserStartedSpeakingFrame():
                self._end_if_pending()  # a pause with nothing transcribed
                self._out.put_nowait(SpeechStartedFrame(at_ms=now))
            case UserStoppedSpeakingFrame() | VADUserStoppedSpeakingFrame():
                self._end_pending = True
            case _:
                pass
        await self.push_frame(frame, direction)

    def _end_if_pending(self) -> None:
        if self._end_pending:
            self._end_pending = False
            self._out.put_nowait(UtteranceEndFrame())


class PipecatTranscriberStream:
    """One pipeline run per ``audio_start``."""

    def __init__(self, processors: list[FrameProcessor], audio: AudioStart) -> None:
        self._audio = audio
        self._out: asyncio.Queue[TranscriberFrame | None] = asyncio.Queue()
        self._sink = TranscriberSink(self._out, audio.sample_rate)
        self._task = PipelineTask(
            Pipeline([*processors, self._sink]),
            params=PipelineParams(audio_in_sample_rate=audio.sample_rate),
            idle_timeout_secs=None,
            enable_rtvi=False,
            check_dangling_tasks=False,
        )
        self._runner = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        # One runner per stream: it ends when the pipeline does, after audio_end.
        runner = WorkerRunner(handle_sigint=False, check_dangling_tasks=False)
        try:
            await runner.add_workers(self._task)
            await runner.run()
        finally:
            self._out.put_nowait(None)

    async def send(self, audio: bytes) -> None:
        self._sink.heard_bytes += len(audio)
        await self._task.queue_frame(
            InputAudioRawFrame(
                audio=audio,
                sample_rate=self._audio.sample_rate,
                num_channels=self._audio.channels,
            )
        )

    async def keepalive(self) -> None:
        pass

    async def finish(self) -> None:
        await self._task.queue_frame(EndFrame())

    async def close(self) -> None:
        await self._task.cancel()

    async def frames(self) -> AsyncIterator[TranscriberFrame]:
        while (frame := await self._out.get()) is not None:
            yield frame


class PipecatTranscriberTopic(TranscriberTopic):
    """Transcribe with the Pipecat processors ``processors`` returns."""

    def processors(self, audio: AudioStart) -> list[FrameProcessor]:
        raise NotImplementedError(
            f"{type(self).__name__} must override processors() to build the pipeline."
        )

    async def open_stream(self, audio: AudioStart) -> PipecatTranscriberStream:
        return PipecatTranscriberStream(self.processors(audio), audio)
