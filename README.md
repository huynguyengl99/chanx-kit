# ChanX Kit

A collection of best-practice, reusable WebSocket components.

[![CI](https://github.com/huynguyengl99/chanx-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/huynguyengl99/chanx-kit/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue)](https://github.com/huynguyengl99/chanx-kit)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[Documentation](https://huynguyengl99.github.io/chanx-kit/)** ·
[Browse the kits](https://huynguyengl99.github.io/chanx-kit/kits/) ·
[Getting started](https://huynguyengl99.github.io/chanx-kit/getting-started/)

Notifications, chat with replayed history, a presence roster, an agent streaming tokens
to the browser: add the one you need, in a single command, and own the code it copies in.
Inspired by [shadcn/ui](https://ui.shadcn.com), but built for WebSocket applications.

```bash
uvx copit add @chanx-kit/notification
```

## What you get

- **The code is yours.** A kit lands in your repository as ordinary classes you can read,
  subclass, or edit outright. No hidden layer, and no waiting for someone to add the hook
  you need.
- **Only the part you need.** Install one kit, not a framework. Your footprint is exactly
  what you used, and nothing is pulled in behind it.
- **Django and FastAPI, same kit.** Kits import only framework-agnostic
  [chanx](https://github.com/huynguyengl99/chanx), so the same component runs on Django
  Channels and on FastAPI / fast-channels.
- **Production-shaped, not demo-shaped.** Authorization per subscription, pluggable
  persistence, and READMEs that say plainly which defaults are single-process. Every kit
  is tested on both backends and type-checked in strict mode.
- **Composable.** Kits are listed on a consumer rather than inherited, so any number of
  them work side by side, and each one still works alone.

Use cases:

- AG-UI agents, and bi-directional agent streaming
- Notifications
- Room chat with replayed history and live presence
- Binary and audio streaming (planned)
- And more ...

## Getting started

**Install chanx**, if you have not yet. It is the only package a kit needs:

```bash
pip install "chanx[fast_channels]"    # FastAPI and other ASGI apps
pip install "chanx[channels]"         # Django
```

**Point [copit](https://github.com/huynguyengl99/copit) at this registry**, once. It
records where kits come from and where they land, in `copit.toml`:

```bash
uvx copit init
uvx copit registry add chanx-kit github:huynguyengl99/chanx-kit@v0.1.0 --to app/ws_kits
```

**Add a kit.** The source is copied into `app/ws_kits/notification/`, along with any kit
it depends on:

```bash
uvx copit add @chanx-kit/notification
```

**List it on a consumer.** A kit is a topic: a pattern clients address, with its own
handlers, authorization and group.

```python
class AppConsumer(AsyncJsonWebsocketConsumer[NotificationMessage]):
    channel_layer_alias = "default"
    topics = [UserNotificationTopic, BroadcastNotificationTopic]
```

**Use it from anywhere.** A signal, a worker or another service can reach connected
clients without importing a consumer:

```python
await UserNotificationTopic.notify_user(
    user.id, NotificationPayload(title="Build finished", level="success")
)
```

From here, the
[getting started guide](https://huynguyengl99.github.io/chanx-kit/getting-started/)
covers subscribing from a client, composing several kits, and overriding a kit's hooks.

## A few kits

| Kit | What it does |
|---|---|
| [`notification`](kits/notification) | Fan out notifications to a user's live connections, from a signal, a worker, or another service |
| [`room_chat`](kits/room_chat) | A chat room: history replayed on connect, plus a live roster. Pluggable store |
| [`ag_ui`](kits/ag_ui) | Serve the AG-UI protocol over a websocket, so any AG-UI frontend works unchanged. Provider-agnostic |

Presence, a Redis-backed roster, a Django-backed message store and the test harness are
kits too. See [kits/](kits) in this repository, or
**[browse them all](https://huynguyengl99.github.io/chanx-kit/kits/)** with their
messages, hooks and caveats.

## Try the demo

```bash
uv sync
npm --prefix sandbox/ui install && npm --prefix sandbox/ui run build
uv run python -m sandbox
```

Open **http://localhost:8000** for one panel per kit, plus
[AsyncAPI docs](http://localhost:8000/asyncapi) for the generated WebSocket API. Open a
second tab in the Room panel to watch history replay and the roster update live.

## Why it exists

Realtime features look different but are built from the same plumbing: group naming,
authorization per subscriber, state on connect, cleanup on disconnect, and a way for a
worker or a signal to reach a live client. Most of us write it again in every project, or
copy it from a tutorial that never mentions what breaks once you run two processes.

The usual escape is a package that does it for you and then owns your consumers. The day
you need to change how a room is authorized, you are reading someone else's source
looking for a hook they did not add. Copying the component in avoids both: you start from
something that already works, and it is yours from the first line.

## Contributing

New kits are welcome, especially ones you already run yourself. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the checklist: a kit needs metadata, a README, and
tests that pass on both backends.

## License

MIT
