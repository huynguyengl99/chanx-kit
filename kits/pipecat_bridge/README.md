# pipecat-bridge

Run a [Pipecat](https://docs.pipecat.ai) pipeline behind a chanx transcriber topic.
Pipecat integrates dozens of speech services; this bridge makes any of its
speech-to-text services speak the [transcriber contract](../audio_stream_in), so the
transcriber and voice-agent UI kits work with it unchanged.

```bash
copit add @chanx-kit/pipecat-bridge
```

```python
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService   # pipecat-ai[deepgram]

from .ws_kits.audio_stream_in import AudioConfig
from .ws_kits.pipecat_bridge import PipecatTranscriberTopic


class MicTopic(PipecatTranscriberTopic):
    # Silero takes 8 or 16 kHz; the browser captures at whatever audio_config says.
    audio_config = AudioConfig(sample_rate=16000)

    def processors(self, audio):
        return [
            VADProcessor(vad_analyzer=SileroVADAnalyzer(sample_rate=audio.sample_rate)),
            DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"], sample_rate=audio.sample_rate),
        ]
```

The `VADProcessor` is what gives turns: its speaking frames become `speech_started` and
`utterance_end`, which the voice agent needs for turns and barge-in. Without it you get
partials and finals, and one utterance per `audio_start` to `audio_end`.

## How it fits

chanx owns the WebSocket, the topic, authentication and limits; Pipecat never sees a
transport. Each `audio_start` builds a pipeline `[*processors(audio), sink]`: audio
chunks are queued in as `InputAudioRawFrame`, and the sink turns
`InterimTranscriptionFrame`, `TranscriptionFrame` and the user speaking frames (a
transport's, or a `VADProcessor`'s) into `transcript_partial`, `transcript_final`,
`speech_started` and `utterance_end`. Voice activity notices a pause before the service
finalizes, so the utterance end is held until the final arrives.
`audio_end` queues an `EndFrame`, so the service flushes before the pipeline stops.

Pipecat is a large dependency (a few hundred MB with its audio stack), so it belongs to
this kit alone; nothing else in chanx-kit needs it.

## Status

Verified on Pipecat 1.12 (2026-09-27): the shared transcriber suite passes through the
bridge with a scripted Pipecat STT service; the pipeline hop adds a median of 0.2 ms per
chunk (p95 0.3 ms); and live, Silero VAD plus Pipecat's `DeepgramSTTService` turned two
spoken sentences into two full turns (speech started, partials, final, utterance end
each). Each stream runs its pipeline on its own `WorkerRunner`. Run the tests with
Pipecat installed; they are skipped without it.
