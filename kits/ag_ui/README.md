# ag-ui

Serve the [AG-UI protocol](https://ag-ui.com) over a chanx websocket, so any AG-UI
frontend works unchanged.

```bash
copit add @chanx-kit/ag-ui
```

## Why over a websocket

AG-UI is normally carried over SSE, which is one-way and needs its own endpoint. On a
chanx websocket it is bidirectional and shares one connection with your other kits, so
a client can be in a chat room *and* driving an agent on the same socket.

Wire compatibility is preserved: the protocol's events travel in `payload`, and a client
switches on `payload.type` exactly as it already does.

## Use it

Subclass the topic to provide `run_agent`, then list it on a consumer:

```python
from ag_ui.core import Event, EventType, RunAgentInput, TextMessageContentEvent
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

from .ws_kits.ag_ui import AgUiEventMessage, AgUiTopic


class MyAgUiTopic(AgUiTopic):
    async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        async for delta in my_agent(run_input.messages):
            yield TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT, message_id="m1", delta=delta
            )


class AgentConsumer(AsyncJsonWebsocketConsumer[AgUiEventMessage]):
    channel_layer_alias = "default"
    topics = [MyAgUiTopic]
```

A client subscribes to `agui:thread:<thread_id>` and sends `ag_ui_run`, so several
conversations can share one connection.

`RUN_STARTED` and `RUN_FINISHED` bracket whatever you yield, and an exception becomes
`RUN_ERROR`, so `run_agent` only has to produce content events.

## Any provider

The kit does not depend on a specific agent framework. `run_agent` is the hook for a
provider you drive yourself: yield content events, and the run is bracketed for you.

### When the provider emits its own lifecycle

An agent framework with AG-UI support of its own already emits `RUN_STARTED` and
`RUN_FINISHED`, and its `RUN_FINISHED` carries the run's outcome — which can mean
more than "done", so it must not be replaced by a synthesised one. Override
`run_events` rather than `run_agent` to pass a provider's whole stream through
untouched:

```python
class MyAgUiTopic(AgUiTopic):
    async def run_events(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        async for event in my_framework_adapter(run_input):
            yield event
```

`run_agent` and `run_events` are the same seam at two heights: implement whichever
matches how much of the protocol your provider already speaks.

## Several tabs on one run

By default a run is written straight down the socket that asked for it. Set
`broadcast_run_events` to let every connection on a thread watch it instead — a
second tab, or the same tab after a refresh:

```python
class MyAgUiTopic(AgUiTopic):
    broadcast_run_events = True
```

Three things change:

- Events go to the thread's group, so the run no longer depends on the connection
  that started it. Close that tab mid-run and the run continues for everyone else.
- Each event carries a per-run `seq` on the chanx envelope, restarting at 1 on
  `RUN_STARTED`. It sits beside the message, not inside `payload`, so the AG-UI event
  is unchanged and a client still switches on `payload.type`.
- A connection subscribing mid-run is replayed the run so far before anything live,
  so it always sees a stream beginning at `RUN_STARTED`. AG-UI has no way to join a
  stream in progress: a content delta before its `TEXT_MESSAGE_START` is malformed.

Replay covers the run in flight only. Once a run finishes its buffer is dropped, and
a connection arriving afterwards should load your stored transcript instead.

### What the client owes you

Replayed and live events share one sequence, so a client applies them in order and
drops what it has already seen:

```ts
let expected = 1
const pending = new Map<number, AgUiEvent>()

function onEvent(seq: number | undefined, event: AgUiEvent) {
  if (seq === undefined) return apply(event)   // not part of a run
  if (event.type === "RUN_STARTED") expected = seq
  if (seq < expected) return                   // already applied via replay
  pending.set(seq, event)
  while (pending.has(expected)) {
    apply(pending.get(expected)!)
    pending.delete(expected++)
  }
}
```

!!! warning
    The default `InMemoryRunEventStore` is process-local. With more than one worker,
    a connection can land on a process that never saw the run, and its replay comes
    back empty. Implement `RunEventStore` against Redis or another shared backend
    before running more than one process.

## Emitting from elsewhere

A worker, a graph node or a tool runner can contribute events without holding the
socket. The caller needs no consumer, only an address, and the client reads one AG-UI
stream and cannot tell which process produced each event. `sandbox/worker.py` is a
runnable example.

**Emit into the conversation.** This is the one to reach for: the client is already
subscribed to the thread, so nothing has to be arranged in advance.

```python
await MyAgUiTopic.emit_to_thread(thread_id, ToolCallStartEvent(...))
```

**Emit into one run.** `AgUiRunTopic` addresses a single execution,
`agui:run:<run_id>`, for when the caller must target *that* run, for example a queued
job keyed by run id, or a UI showing per-run progress while two runs share a thread.

```python
await AgUiRunTopic.emit_to_run(run_id, ToolCallStartEvent(...))
```

It costs a little more setup: list `AgUiRunTopic` on the consumer, and have the client
subscribe to `agui:run:<id>` **before** it sends `ag_ui_run`. Groups do not buffer, so
anything emitted before that subscription lands is lost. That also means the client
should send its own `runId` rather than letting the server generate one, since a
generated id only reaches the client with `RUN_STARTED`, by which point it is too late.

Neither route is ordered against the connection's own events. A topic's own events go
straight down its socket, so a run never reorders itself, but anything arriving through
the channel layer can interleave. Emit from elsewhere for work that is genuinely
concurrent, not to split one sequential stream across processes.

## camelCase, and why not `camelize`

AG-UI is camelCase on the wire (`messageId`, `threadId`). This kit serialises with
Pydantic aliases, which rename only declared fields.

!!! warning
    Do **not** enable chanx's `camelize` for this consumer. It rewrites every key it
    sees, including the opaque `state` and `forwardedProps` payloads that belong to
    your agent, where `API_KEY_ref` would silently become `APIKEYRef`. Aliases leave them
    untouched.

Set `send_by_alias = False` only if you are deliberately talking to a non-AG-UI client.

## Messages

| Action | Direction | Payload |
|---|---|---|
| `ag_ui_run` | client → server | AG-UI `RunAgentInput`: thread and run ids, messages, state, tools |
| `ag_ui_event` | server → client | AG-UI `Event`: the full union, keyed on `type` |

## Customise

| Hook | Default | Purpose |
|---|---|---|
| `run_agent(run_input)` | raises | Produce the run's content events |
| `run_events(run_input)` | brackets `run_agent` | Produce the run's whole stream, lifecycle included |
| `on_run_error(input, err)` | sends `RUN_ERROR` | Log, or hide provider detail |
| `new_run_id()` | uuid4 hex | Run ids when the client omits one |
| `broadcast_run_events` | `False` | Let every connection on the thread watch the run |
| `run_event_store` | `InMemoryRunEventStore()` | Where a run is buffered for replay |
| `send_by_alias` | `True` | Turn off only for a non-AG-UI client |
