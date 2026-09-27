# ElevenLabs

[ElevenLabs](https://elevenlabs.io): realtime speech-to-text (Scribe) and streaming text-to-speech, each behind its [contract](../audio_stream_in), so any transcriber or player
UI works with it and switching provider is one class.

```bash
copit add @chanx-kit/elevenlabs                 # both parts
copit add @chanx-kit/elevenlabs --only stt      # speech-to-text only
copit add @chanx-kit/elevenlabs --only tts      # text-to-speech only
```

| Part | Module | Contract | Needs |
|---|---|---|---|
| `stt` | `transcriber.py` | transcriber@1 | [`audio-stream-in`](../audio_stream_in) |
| `tts` | `synthesizer.py` | synthesizer@1 | [`audio-stream-out`](../audio_stream_out) |

Leaving a part out also leaves out the base kit only it needs. Import from the part's
module (`from .ws_kits.elevenlabs.transcriber import ...`), since the other may not be there.
Picking parts needs copit 0.9; older copit installs both.

Set `ELEVENLABS_API_KEY` in the server's environment; the browser never sees it.

## Speech to text

Live speech-to-text with [ElevenLabs Scribe realtime](https://elevenlabs.io/docs) behind
the [transcriber contract](../audio_stream_in): any transcriber UI works with it, and
switching from Deepgram is one class.

```python
from .ws_kits.elevenlabs.transcriber import ElevenLabsTranscriberTopic

class MicTopic(ElevenLabsTranscriberTopic):
    options = {"vad_silence_threshold_secs": "0.8"}
```

Set `ELEVENLABS_API_KEY` on the server. Audio goes to Scribe as base64 PCM at the
negotiated rate (`pcm_24000` by default); `commit_strategy=vad` lets Scribe end
utterances on silence.

| Scribe | transcriber@1 |
|---|---|
| first `partial_transcript` of an utterance | `speech_started` |
| `partial_transcript` | `transcript_partial` |
| `committed_transcript` | `transcript_final`, then `utterance_end` |
| empty chunk with `commit` on `audio_end` | last words flushed, then the stream closes |

Scribe sends no speech-started event, so the adapter reports speech starting at an
utterance's first partial transcript. That is a fraction of a second later than a
dedicated voice activity event, which is enough for the voice agent's barge-in.

Verified against the live service (2026-09-27, free tier): partials growing into one
committed transcript, with `speech_started` from the first partial.

## Text to speech

Streaming text-to-speech with [ElevenLabs](https://elevenlabs.io) behind the
[synthesizer contract](../audio_stream_out), so any player UI works with it and you can
switch providers by changing one class.

```python
from .ws_kits.elevenlabs.synthesizer import ElevenLabsSynthesizerTopic

class ReplyVoiceTopic(ElevenLabsSynthesizerTopic):
    default_voice = "EXAVITQu4vr4xnSDxMaL"   # Sarah, premade
    model_id = "eleven_flash_v2_5"

await ReplyVoiceTopic.speak(session_id, "Hello from the server.")
```

Set `ELEVENLABS_API_KEY` in the server's environment; the browser never sees it. Audio
is requested as raw PCM (`pcm_24000` by default, matching `output_format`), so nothing
is decoded on the way: ElevenLabs' base64 audio becomes bytes, re-cut into whole frames
and streamed to every listener. A client may pick a voice per `speak`.

The adapter speaks the `stream-input` WebSocket with `websockets` directly, no SDK: an
opening message with `voice_settings`, the text with `flush`, then empty text to end,
reading `audio` until `isFinal`.

Verified against the live service (2026-09-27, free tier): first audio after about
0.4 s, and it speaks into the sandbox's player and voice agent in a browser. Use a
premade voice on the free tier: others answer `payment_required`, which the adapter
reports as `provider_unavailable` with that hint.
