# django-message-store

Durable chat history in your Django database, with an admin and a read-only REST
endpoint.

```bash
copit add @chanx-kit/django-message-store --variant django   # also installs: room-chat
```

**Django only.** This kit ships models, migrations, admin and a DRF viewset, none of
which have a fast-channels equivalent, so it declares `only_variants: [django]` and
copit refuses to install it into a project that has not selected that variant.

## Why

The `room-chat` kit defaults to `InMemoryMessageStore`, a bounded deque per room. It
loses everything on restart and each worker holds its own copy, so which history a
client gets depends on which worker answered. This keeps it in your database instead.

## Use it

Add the app and run its migration:

```python
INSTALLED_APPS = [..., "rest_framework", "app.ws_kits.django_message_store"]
```

```bash
python manage.py migrate
```

```python
from app.ws_kits.django_message_store.store import DjangoMessageStore
from app.ws_kits.room_chat import RoomChatTopic


class DurableChatTopic(RoomChatTopic):
    message_store = DjangoMessageStore()
```

Nothing else changes: it satisfies the same `MessageStore` protocol.

The store is imported from `.store`, not from the package. A Django app's `__init__` is
imported before the app registry is ready, so re-exporting a model from there raises
`AppRegistryNotReady` at startup.

## The history API

```python
path("api/chat/", include("app.ws_kits.django_message_store.urls")),
```

```
GET /api/chat/history/?room=general&page_size=50
```

Paginated, newest first. `id` is the kit's own entry id, the same one the message
carried over the websocket, so a client can match the two. It is **read-only**: a
message created here would be persisted without any connected client being told, so
posting is 405. Add permission classes to the viewset if history is not public.

## What is stored

`ChatEntryRecord` flattens `ChatEntry`: `entry_id`, `room`, `author_id`, `author_name`,
`body`, `sent_at`, indexed on `(room, -sent_at)`. The model is deliberately not the
wire contract. That belongs to `room-chat`, so a schema change here cannot alter what
clients receive.

## Trade-offs

- Every message costs a write. For very busy rooms, batch or queue the append.
- `backlog()` reads the latest `limit` rows and reverses them in Python, which is fine
  for the tens of messages a client replays. Paginate through the REST endpoint for
  anything larger.
- History grows without bound. Add a retention job if that matters.
