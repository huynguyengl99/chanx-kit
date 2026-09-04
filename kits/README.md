# kits

Each subdirectory is one **kit**: a self-contained WebSocket component you copy into your
project and then own.

```bash
copit add @chanx-kit/notification
```

Nothing here is installed as a package. A copied kit depends on
[chanx](https://github.com/huynguyengl99/chanx) alone, and even the test harness is a kit.

Every kit's own README covers its messages, hooks and caveats. The
[docs site](https://huynguyengl99.github.io/chanx-kit/kits/) has the same pages, plus
search and generated message schemas.

## Messaging

| Kit | Tier | What it does |
|---|---|---|
| [`notification`](notification) | core | Fan out notifications to a user's live connections, from a signal, a worker or another service |
| [`room_chat`](room_chat) | core | A chat room: history replayed on connect, plus a live roster. Pluggable store |

## Presence

| Kit | Tier | What it does |
|---|---|---|
| [`presence`](presence) | core | Who is in a room, document or tenant, and join/leave events. Ships an in-process store |
| [`redis_presence_store`](redis_presence_store) | contrib | Swaps that store for Redis, so presence stays correct across workers |

## Agents

| Kit | Tier | What it does |
|---|---|---|
| [`ag_ui`](ag_ui) | core | Serve the AG-UI protocol over a websocket, for any AG-UI frontend. Provider-agnostic |

## Django only

| Kit | Tier | What it does |
|---|---|---|
| [`django_message_store`](django_message_store) | contrib | Chat history in your database, with an admin and a REST endpoint |

Most kits run on both backends. This one ships models, migrations and framework-specific
views with no fast-channels equivalent, so it declares the variant it needs and copit
refuses to install it elsewhere:

```bash
copit add @chanx-kit/django-message-store --variant django
```

## Tooling

| Kit | Tier | What it does |
|---|---|---|
| [`chanx_testing`](chanx_testing) | core | Backend-agnostic test harness, installed with `--with tests` |

## Tiers and dependencies

`core` is the primary set: portable across both backends, and a `core` kit may only depend
on other `core` kits. `contrib` is everything else: optional adapters that swap a default
(`redis_presence_store`), kits tied to one framework (`django_message_store`), and new
kits still proving themselves. Same review and the same CI, just outside what core
promises.

Tier is metadata rather than part of the id, so promoting a kit does not change how anyone
installs it.

Kits may build on each other, as `room_chat` does on `presence`, and copit installs the
dependency for you.

## Adding or changing a kit

See [../CONTRIBUTING.md](../CONTRIBUTING.md) for the checklist, and
[../docs/authoring-a-kit.md](../docs/authoring-a-kit.md) for what a topic is made of and
why. The naming, layout and packaging rules this directory follows are recorded in
[../docs/registry-conventions.md](../docs/registry-conventions.md).
