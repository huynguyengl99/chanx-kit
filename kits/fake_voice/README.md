# Fake voice

No provider and no key: a scripted transcriber and a tone-per-word synthesizer, for demos, UI work and CI, each behind its [contract](../audio_stream_in), so any transcriber or player
UI works with it and switching provider is one class.

```bash
copit add @chanx-kit/fake-voice                 # both parts
copit add @chanx-kit/fake-voice --only stt      # speech-to-text only
copit add @chanx-kit/fake-voice --only tts      # text-to-speech only
```

| Part | Module | Contract | Needs |
|---|---|---|---|
| `stt` | `transcriber.py` | transcriber@1 | [`audio-stream-in`](../audio_stream_in) |
| `tts` | `synthesizer.py` | synthesizer@1 | [`audio-stream-out`](../audio_stream_out) |

Leaving a part out also leaves out the base kit only it needs. Import from the part's
module (`from .ws_kits.fake_voice.transcriber import ...`), since the other may not be there.
Picking parts needs copit 0.9; older copit installs both.

## Speech to text

A [transcriber](../audio_stream_in) that needs no provider and no key. Any speech is
transcribed as a scripted sentence, one word per `ms_per_word` of loud audio, so
partials grow while you speak and finals land in the same place every run. A simple
voice activity detector ends an utterance after `silence_ms` (600) of quiet, the way
real providers do, so an open microphone produces turns and the voice agent answers
them. Use it to build and
test a voice UI, in CI, and in demos, then swap in a real provider kit without changing
the client.

```python
from .ws_kits.fake_voice.transcriber import FakeTranscriberTopic

class DemoTranscriberTopic(FakeTranscriberTopic):
    script = "the quick brown fox jumps over the lazy dog".split()
```

List it on a consumer next to `TranscriptTopic`, exactly as you would a real provider.
Tune `speech_level` (RMS in PCM16 units, default 500) if your microphone is quiet.
It sets no time or session limits, since it costs nothing.

## Text to speech

A [synthesizer](../audio_stream_out) that needs no provider and no key. Any text is
spoken as a short tone per word, streamed at the pace of speech, so a player, a voice
UI or a test sees real audio flow, queueing and interruption without an account. Swap
in a real provider kit later without touching the client.

```python
from .ws_kits.fake_voice.synthesizer import FakeSynthesizerTopic

class DemoSynthesizerTopic(FakeSynthesizerTopic):
    pace = 1.0   # real time; 0 sends each utterance at once (tests)
```
