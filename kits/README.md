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
| [`pydantic_ai_ag_ui`](pydantic_ai_ag_ui) | contrib | A Pydantic AI agent over AG-UI, conversation kept server-side |

## Voice

Contracts first, providers second: every provider kit passes its contract's shared test
suite, so switching provider is one class and the UI does not change.

| Kit | Tier | What it does |
|---|---|---|
| [`media_stream_in`](media_stream_in) | core | Bytes over JSON, chunks back in order, a bounded real-time intake |
| [`audio_stream_in`](audio_stream_in) | core | Microphone audio in, transcripts out: defines `transcriber@1` |
| [`media_stream_out`](media_stream_out) | core | Server-side producers in order per session, replay for late joiners |
| [`audio_stream_out`](audio_stream_out) | core | Text in, audio out to every listener: defines `synthesizer@1` |
| [`voice_agent`](voice_agent) | core | Talk to any AG-UI agent: turns, spoken replies, barge-in |

One kit per provider, with a speech-to-text part (`stt`) and a text-to-speech part
(`tts`). Both install by default; `--only stt` or `--only tts` keeps one, and leaves out
the base kit only the other needs.

| Kit | Tier | What it does |
|---|---|---|
| [`fake_voice`](fake_voice) | core | Scripted transcripts and tone-per-word speech, no key: demos, UI work, CI |
| [`deepgram`](deepgram) | contrib | Deepgram Nova speech-to-text and Aura text-to-speech |
| [`elevenlabs`](elevenlabs) | contrib | ElevenLabs Scribe realtime and streaming text-to-speech |
| [`openai`](openai) | contrib | OpenAI realtime transcription and text-to-speech |
| [`pipecat_bridge`](pipecat_bridge) | contrib | Any Pipecat speech-to-text service behind `transcriber@1` |

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
