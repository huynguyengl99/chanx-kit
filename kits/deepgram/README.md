# Deepgram

[Deepgram](https://deepgram.com): live speech-to-text (Nova) and streaming text-to-speech (Aura), each behind its [contract](../audio_stream_in), so any transcriber or player
UI works with it and switching provider is one class.

```bash
copit add @chanx-kit/deepgram                 # both parts
copit add @chanx-kit/deepgram --only stt      # speech-to-text only
copit add @chanx-kit/deepgram --only tts      # text-to-speech only
```

| Part | Module | Contract | Needs |
|---|---|---|---|
| `stt` | `transcriber.py` | transcriber@1 | [`audio-stream-in`](../audio_stream_in) |
| `tts` | `synthesizer.py` | synthesizer@1 | [`audio-stream-out`](../audio_stream_out) |

Leaving a part out also leaves out the base kit only it needs. Import from the part's
module (`from .ws_kits.deepgram.transcriber import ...`), since the other may not be there.
Picking parts needs copit 0.9; older copit installs both.

Set `DEEPGRAM_API_KEY` in the server's environment; the browser never sees it.

## Speech to text

Live speech-to-text with [Deepgram](https://deepgram.com) behind the
[transcriber contract](../audio_stream_in), so any transcriber UI works with it and you
can switch providers by changing one class.

```python
from .ws_kits.audio_stream_in import TranscriptTopic
from .ws_kits.deepgram.transcriber import DeepgramTranscriberTopic

class VoiceTranscriberTopic(DeepgramTranscriberTopic):
    model = "nova-3"
    options = {"smart_format": "true"}

    async def authorize(self, **params: str) -> bool:
        return await user_owns_session(self.scope, params["session"])

class VoiceConsumer(AsyncJsonWebsocketConsumer):
    topics = [VoiceTranscriberTopic, TranscriptTopic]
```

Set `DEEPGRAM_API_KEY` in the server's environment. The browser never sees it: it
streams to your chanx server, which holds the Deepgram connection. Without a key the
topic reports `provider_unavailable` on subscribe rather than failing at import.

### How it maps

| Deepgram | transcriber@1 |
|---|---|
| interim `Results` | `transcript_partial` |
| `Results` with `is_final` | `transcript_final` |
| `speech_final`, `UtteranceEnd` | `utterance_end` |
| `SpeechStarted` (`vad_events`) | `speech_started` |
| `KeepAlive` while no audio arrives | (kept open during pauses) |
| `Finalize` then `CloseStream` on `audio_end` | last finals, then the stream closes |

Audio goes up as binary frames, which is Deepgram's native format: base64 is only on
the browser-to-chanx leg.

The adapter speaks Deepgram's WebSocket protocol with `websockets` directly, no SDK.
Its tests run against a local server replaying the documented protocol, plus the
shared transcriber contract suite.

Verified against the live service (2026-09-27, `scripts/live_check.py deepgram`, and
the sandbox in a browser): speech-started events, partials, finals and utterance ends,
with a two-sentence line split into two turns at the pause.

## Text to speech

Streaming text-to-speech with [Deepgram Aura](https://deepgram.com) behind the
[synthesizer contract](../audio_stream_out).

```python
from .ws_kits.deepgram.synthesizer import DeepgramSynthesizerTopic

class ReplyVoiceTopic(DeepgramSynthesizerTopic):
    default_voice = "aura-2-thalia-en"   # the voice is the model
```

Set `DEEPGRAM_API_KEY` on the server; the same key serves the Deepgram transcriber.
Each utterance opens the `speak` WebSocket with `encoding=linear16` at the output rate,
sends `Speak` and `Flush`, streams the binary audio until `Flushed`, then `Close`s.

Verified against the live service (2026-09-27): Aura speech for a two-sentence line,
transcribed back by the Deepgram transcriber.
