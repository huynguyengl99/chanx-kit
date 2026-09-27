# media-stream-out

The plumbing for media the server streams out over a chanx websocket. It has no topic
of its own: [`audio-stream-out`](../audio_stream_out) builds the synthesizer on it.

```bash
copit add @chanx-kit/media-stream-out
```

## One producer at a time, per session

`SerialJobs` runs jobs per key in submission order, one at a time. A spoken reply needs
exactly that: an agent queues sentence after sentence and they play in order, and an
interruption (`cancel(key)`) stops the one playing and drops the rest. Jobs run in the
process that submitted them and reach clients through the channel layer.

## Replay for late joiners

A second tab joining while audio is streaming has missed its start, and audio cannot be
picked up part-way. `ReplayStore` keeps what was sent on the stream in flight, numbered
from 1, so a joiner is replayed it and then continues live, the same way the ag-ui kit
replays a run. `InMemoryReplayStore` is process-local and bounded; implement the
protocol against Redis when producers and connections live in different processes.
