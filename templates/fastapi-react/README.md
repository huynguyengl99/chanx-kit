# chanx app

FastAPI on [chanx](https://github.com/huynguyengl99/chanx) and React on
[chanx-js](https://github.com/huynguyengl99/chanx-js), with the
[ChanX Kit](https://github.com/huynguyengl99/chanx-kit) `notification` kit wired end to
end. The client is typed from the server's AsyncAPI schema.

Needs [uv](https://docs.astral.sh/uv/) and Node 20.19+.

## Run

```bash
uv sync
npm --prefix web install

uv run uvicorn app.main:app --reload     # API + WebSocket on :8000
npm --prefix web run dev                 # UI on http://localhost:5173
```

Open two tabs and send a notification: both get it. "Only to" reaches just that user.
API docs: http://localhost:8000/asyncapi.

Single port: `npm --prefix web run build`, then run uvicorn alone.

## From another process

```bash
docker compose up -d
REDIS_URL=redis://localhost:6399/0 uv run uvicorn app.main:app --reload
REDIS_URL=redis://localhost:6399/0 uv run python -m app.notify "Build finished"
```

## Layout

| Path | |
| --- | --- |
| `app/consumers.py` | Consumer and the kit topics it lists |
| `app/main.py` | Routes, including `POST /api/notify` |
| `app/ws_kits/` | Kits copied by copit, yours to edit |
| `web/src/generated/` | Typed client, from `npm --prefix web run gen` |
| `web/src/chanx-kit/` | Kit UI: hooks and components |
| `copit.toml` | Kit sources, for `copit update` |

## Add a kit

```bash
uvx copit add @chanx-kit/room-chat
```

1. List its topics on a consumer in `app/consumers.py`.
2. `npm --prefix web run gen`.
3. Use the new topics from `@/generated` with `useTopic` / `useTopics` from
   `@chanx-js/client/react`.

Kits: https://huynguyengl99.github.io/chanx-kit/kits/

## Auth

Users are identified by `?as=<name>`. Replace `AppUserNotificationTopic.current_user_id`
in `app/consumers.py` with your auth.
