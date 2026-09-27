# OpenAI

OpenAI: realtime transcription and text-to-speech, each behind its [contract](../audio_stream_in), so any transcriber or player
UI works with it and switching provider is one class.

```bash
copit add @chanx-kit/openai                 # both parts
copit add @chanx-kit/openai --only stt      # speech-to-text only
copit add @chanx-kit/openai --only tts      # text-to-speech only
```

| Part | Module | Contract | Needs |
|---|---|---|---|
| `stt` | `transcriber.py` | transcriber@1 | [`audio-stream-in`](../audio_stream_in) |
| `tts` | `synthesizer.py` | synthesizer@1 | [`audio-stream-out`](../audio_stream_out) |

Leaving a part out also leaves out the base kit only it needs. Import from the part's
module (`from .ws_kits.openai.transcriber import ...`), since the other may not be there.
Picking parts needs copit 0.9; older copit installs both.

Set `OPENAI_API_KEY` in the server's environment; the browser never sees it.

## Speech to text

Live speech-to-text with OpenAI's
[realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription)
behind the [transcriber contract](../audio_stream_in).

```python
from .ws_kits.openai.transcriber import OpenAITranscriberTopic

class MicTopic(OpenAITranscriberTopic):
    model = "gpt-4o-transcribe"
    turn_detection = {"type": "server_vad"}   # turns end on silence
```

Set `OPENAI_API_KEY` on the server. OpenAI realtime takes PCM16 mono at 24 kHz, the
kit's default format.

| OpenAI | transcriber@1 |
|---|---|
| `...input_audio_transcription.delta` | `transcript_partial` (the turn's text so far) |
| `...input_audio_transcription.completed` | `transcript_final`, then `utterance_end` |
| `input_audio_buffer.speech_started` (with `server_vad`) | `speech_started` |
| `input_audio_buffer.commit` on `audio_end` | the turn is transcribed, then the stream closes |

With `turn_detection = None` (the default) one `audio_start` to `audio_end` is one
turn; with `server_vad` OpenAI splits turns on silence and reports speech starting,
which the voice agent uses for barge-in.

| `model` | `turn_detection = None` | `server_vad` |
|---|---|---|
| `gpt-live-transcribe` (default) | yes | refused by OpenAI |
| `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` | yes | yes |

For a voice agent, use `gpt-4o-transcribe` with `server_vad`.

Verified against the live service (2026-09-27): partials, finals and utterance ends
with the default model; speech-started events and turns split at pauses with
`gpt-4o-transcribe` and `server_vad`.

## Text to speech

Text-to-speech with OpenAI behind the [synthesizer contract](../audio_stream_out).

```python
from .ws_kits.openai.synthesizer import OpenAISynthesizerTopic

class ReplyVoiceTopic(OpenAISynthesizerTopic):
    model = "gpt-4o-mini-tts"
    default_voice = "alloy"
    instructions = "Friendly and brisk."
```

Set `OPENAI_API_KEY` on the server. Each utterance is one streamed request to
`/v1/audio/speech` with `response_format: "pcm"`, which is raw PCM16 mono at 24 kHz, the
kit's default output, so audio reaches listeners as it arrives with nothing to decode.
It uses `httpx`; set `transport` to test without a network.

Verified against the live service (2026-09-27): 4.5 s of speech for a two-sentence
line, first audio after about 2 s, transcribed back by the OpenAI transcriber.
