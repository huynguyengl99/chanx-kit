# sandbox

A FastAPI app with every kit mounted, plus the UI that drives them. It is not published
or copied anywhere: it exists so the kits can be run for real, and it does two jobs
beyond the demo.

1. **The reference for composing kits.** `consumers.py` is what a real project's
   consumers should look like, with independent kits listed side by side.
2. **The source of the wire contract.** The TypeScript client is generated from this
   app's AsyncAPI schema, so a change to any kit's messages shows up as a TypeScript
   diff rather than a runtime surprise.

## Run it

```bash
uv sync
npm --prefix sandbox/ui install && npm --prefix sandbox/ui run build
uv run python -m sandbox
```

Open **http://localhost:8000** for one panel per kit, and
**http://localhost:8000/asyncapi** for the generated WebSocket API docs. The startup
banner tells you which channel layer is active and whether the UI has been built.

For UI work, run Vite separately so you get hot reload. It proxies `/ws` to the server:

```bash
uv run python -m sandbox          # terminal 1
npm --prefix sandbox/ui run dev   # terminal 2, http://localhost:5173
```

## Routes

| Path | Consumer | Kits |
|---|---|---|
| `/ws/notifications` | `NotificationConsumer` | notification |
| `/ws/rooms/{room}` | `RoomConsumer` | room-chat, presence |
| `/ws/agent` | `AgentConsumer` | ag-ui |

Open a second tab on the Room panel to watch history replay and the roster update live.

## Across processes

The default channel layer is in-memory, so it cannot leave the process. To see a worker
reach the browser, give both sides the same Redis:

```bash
docker compose up -d
REDIS_URL=redis://localhost:6399/0 uv run python -m sandbox
REDIS_URL=redis://localhost:6399/0 uv run python -m sandbox.send_notification "Build finished"
```

That reaches every open tab, on `notification:all`. To address one audience instead, and
watch the server refuse a client that asks for someone else's:

```bash
REDIS_URL=redis://localhost:6399/0 uv run python -m sandbox.send_notification --user demo "Just for you"
```

`send_notification.py` is the shape of a Django signal or a Celery task: no WebSocket and
no consumer, just a topic. `worker.py` is the same idea for an agent run: start one in the
UI, then feed tool calls and streamed text into it from another process.

```bash
REDIS_URL=redis://localhost:6399/0 uv run python -m sandbox.worker <run-id>
```

Both publish through the same topic classes `consumers.py` mounts, and that matters:
group names are namespaced by class name, so `DemoUserNotificationTopic` and the
`UserNotificationTopic` it subclasses address different groups. Publishing from the wrong
one is silent, since a broadcast with no subscribers is not an error.

## Files

| File | What it is |
|---|---|
| `consumers.py` | Every kit composed onto three consumers. Start here |
| `main.py` | The FastAPI app, WebSocket routes and AsyncAPI docs |
| `layers.py` | Redis when `REDIS_URL` is set, in-memory otherwise |
| `__main__.py` | `python -m sandbox`, with the startup banner |
| `send_notification.py`, `worker.py` | Publishing from outside the web process |
| `ui/` | The React demo, with `src/generated/` written by the codegen |

## After changing a kit

Regenerate the client, or CI fails on the diff:

```bash
npm --prefix sandbox/ui run gen
```

A new kit also has to be mounted in `consumers.py`. A kit that is absent from this app is
absent from the AsyncAPI schema and therefore has no contract check at all, so
`tests/test_sandbox.py` asserts every kit's messages are reachable from here.
