# media-stream-in

The plumbing for media a client streams in over a chanx websocket. It has no topic of
its own: [`audio-stream-in`](../audio_stream_in) builds the transcriber on it, and your
own media kits can too.

```bash
copit add @chanx-kit/media-stream-in
```

## Bytes on a JSON wire

A chanx message is a JSON text frame, and JSON has no bytes type, so binary data travels
as standard base64. Declare it with `Base64Data` and handlers get real `bytes`:

```python
from .ws_kits.media_stream_in import Base64Data

class AudioChunk(BaseModel):
    index: int
    data: Base64Data  # bytes in Python, base64 on the wire
```

Use it rather than Pydantic's `Base64Bytes`, which decodes whatever it is given: build a
message from real audio in Python with `Base64Bytes` and the raw bytes are read as
base64 text, so the client receives garbage. `Base64Data` keeps raw bytes raw and
decodes only text. It is the same encoding OpenAI Realtime and ElevenLabs use, and it
costs about a third more bytes (24 kHz PCM16 mono is 48 KB/s raw, 64 KB/s as base64).

## Chunks in order

chanx runs each incoming frame as its own task. That keeps arrival order in practice
but does not promise it, so number your chunks and pass them through a
`ChunkSequencer`: early chunks wait for the ones before them, and once more than
`window` are waiting the missing ones are reported as a `Gap` instead of being silently
skipped.

```python
ready, gaps = sequencer.push(message.payload.index, message.payload.data)
```

## A real-time intake

`MediaIntake` feeds chunks to one consumer task in order without ever blocking the
socket. It is bounded, and a full queue drops the **oldest** chunk (late media is
worthless). While nothing arrives it calls `on_quiet("keepalive")` every
`keepalive_seconds`, which is how a provider stream is kept open, and
`on_quiet("idle")` once `idle_seconds` pass, after which it stops.
