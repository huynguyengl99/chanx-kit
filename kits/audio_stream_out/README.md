# audio-stream-out

Speak text to everyone on a session over a chanx websocket, from any text-to-speech
provider. This kit defines the **synthesizer contract** (`synthesizer@1`) and does
everything around the provider: queueing, interruption, replay, playback marks. A
provider kit only produces audio:

| Provider kit | |
|---|---|
| [`fake-voice`](../fake_voice) | tones, no key: demos, UI work, CI |
| [`deepgram`](../deepgram), [`elevenlabs`](../elevenlabs), [`openai`](../openai) | their `tts` part |

```bash
copit add @chanx-kit/fake-voice --only tts   # pulls in audio-stream-out and media-stream-out
```

## Speaking from anywhere

Speaking runs on the server, not on a connection: `speak()` is a classmethod, so a
client's `speak` message, an agent, or a worker can make a session talk, the way
`notify_user()` reaches a user.

```python
await MySynthesizerTopic.speak(session_id, "Your build finished.")
await MySynthesizerTopic.clear(session_id)   # stop now: an interruption
```

Utterances play in the order they were queued. Audio reaches every subscriber of
`speak:<session>` through the channel layer, so the producer and the listeners need not
share a process.

## The conversation

| Action | Direction | |
|---|---|---|
| `speak` | client to server | `text`, `voice`, `utterance_id` (all but `text` optional) |
| `speak_clear` | client to server | stop the utterance playing and the queue |
| `playback_mark` | client to server | `utterance_id`, `played_ms`: what was actually heard |
| `audio_start` | server to client | the format (PCM16 mono 24 kHz by default), `utterance_id`, `text` |
| `audio_chunk` | server to client | `utterance_id`, `index` from 0, `data` (bytes, base64 on the wire) |
| `audio_end` | server to client | `utterance_id`, `duration_ms` |
| `clear` | server to client | drop everything buffered: an interruption |
| `synthesizer_error` | server to client | `provider_unavailable`, `bad_request`, `provider_failed` |

Whatever the provider sends, audio is re-cut into whole PCM16 frames of at most
`max_chunk_ms` (200 ms), so a provider chunk that ends mid-sample never garbles the
next one.

## Late joiners

A tab that subscribes while an utterance is streaming is replayed it from its
`audio_start`, with `seq` on every frame and `index` on every chunk, so it can drop what
it already has. `replay_store` is process-local by default; implement `ReplayStore`
against Redis when speaking and listening happen in different processes.

## What was heard

Clients send `playback_mark` as they play. `playback_store` keeps each utterance's text,
duration and how much was played, and `heard_text()` cuts the text at the matching word.
The voice agent uses it to trim an interrupted reply to what the user heard.

## Limits

`max_text_chars` (2000) refuses longer text instead of billing it; split long text and
speak it in turns. Override `authorize` so only the session's participants may subscribe
or speak.
