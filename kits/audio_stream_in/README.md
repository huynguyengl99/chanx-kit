# audio-stream-in

Stream microphone audio in over a chanx websocket and get transcripts back, from any
speech-to-text provider. This kit defines the **transcriber contract** (`transcriber@1`)
and does everything around the provider: format negotiation, ordering, limits,
keepalive, fan-out. A provider kit only opens a stream:

| Provider kit | |
|---|---|
| [`fake-voice`](../fake_voice) | scripted, no key: demos, UI work, CI |
| [`deepgram`](../deepgram), [`elevenlabs`](../elevenlabs), [`openai`](../openai) | their `stt` part |
| [`pipecat-bridge`](../pipecat_bridge) | any Pipecat speech-to-text service |

```bash
copit add @chanx-kit/fake-voice --only stt   # pulls in audio-stream-in and media-stream-in
```

## Two topics

| Topic | Pattern | Who | Direction |
|---|---|---|---|
| `TranscriberTopic` | `transcribe:{session}` | the session's owner | audio in, transcripts and errors out |
| `TranscriptTopic` | `transcript:{session}` | anyone `authorize` admits | transcripts out only |

Sending audio and reading captions need different permissions, so they are separate
topics. Override `authorize` on both: by default anyone may subscribe.

```python
class VoiceConsumer(AsyncJsonWebsocketConsumer):
    topics = [MyTranscriberTopic, TranscriptTopic]
```

## The conversation

1. On subscribe the server sends `audio_config`: PCM16 mono at 24 kHz and 100 ms
   chunks by default, the one format Deepgram, ElevenLabs and OpenAI all take.
2. The client sends `audio_start` with the format it captured (a mismatch is
   `bad_format`), then `audio_chunk`s numbered from 0, then `audio_end`.
3. The server sends `speech_started`, `transcript_partial` (the segment being spoken,
   replacing the previous partial), `transcript_final` (a segment that will not change)
   and `utterance_end`. An utterance is its finals in order, under one `utterance_id`.

Chunks carry bytes as base64 (see [`media-stream-in`](../media_stream_in)); handlers
and providers see `bytes`. Chunks sent right behind `audio_start` are kept while the
provider connects, and chunks that arrive out of order are put back in order; ones that
never arrive are reported as `audio_gap` rather than fed to the provider as silence it
never heard.

## Limits

Providers bill per second of audio, whoever is logged in, so every stream is bounded:

| Attribute | Default | |
|---|---|---|
| `max_session_seconds` | 300 | one stream's length |
| `idle_timeout_seconds` | 15 | no audio for this long closes the stream |
| `max_sessions_per_user` | 2 | per `current_user_id()`, or per connection without one |
| `keepalive_seconds` | 4 | the provider is kept open while the user pauses |

Set any to `None` to turn it off. A limit that trips sends `transcriber_error` with
`limit_reached`. Streams live in the process holding the socket, since the audio
arrives there; only transcripts cross processes, through the channel layer.

## Doing more with transcripts

Every transcript goes through a hook, then to this connection and to
`transcript:<session>` watchers. Override a hook to store text, start an agent run, or
filter:

```python
class MyTranscriberTopic(DeepgramTranscriberTopic):
    async def on_final(self, transcript: TranscriptFinal) -> None:
        await super().on_final(transcript)
        await save_line(self.session_id, transcript.text)
```

`on_speech_started`, `on_partial`, `on_final`, `on_utterance_end` and `on_gap` are all
overridable. If you subclass `TranscriptTopic`, point `transcript_topic` at your
subclass: group names carry the class name.

## Writing a provider

Subclass `TranscriberTopic` and return a `TranscriberStream` from `open_stream`: it
takes audio (`send`), keeps alive, finishes or closes, and yields frames
(`SpeechStartedFrame`, `PartialFrame`, `FinalFrame`, `UtteranceEndFrame`). Then run the
shared suite against it, the way every provider here does:

```python
from ..audio_stream_in.tests.contract import TranscriberContract

class TestMyProvider(TranscriberContract):
    @pytest.fixture
    def transcriber_topic(self):
        return MyProviderTopic  # set up to hear "hello world" in the suite's audio
```
