# presence

Track who is present in a room, document or tenant, and tell everyone when that changes.

```bash
copit add @chanx-kit/presence
```

## Use it

List the topic on a consumer and add the presence events to its event union:

```python
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

from .ws_kits.presence import PresenceJoinMessage, PresenceLeaveMessage, PresenceTopic


class RoomConsumer(
    AsyncJsonWebsocketConsumer[PresenceJoinMessage | PresenceLeaveMessage]
):
    channel_layer_alias = "default"
    topics = [PresenceTopic]
```

A client subscribes to `presence:<scope>` (a room, a document, a tenant) and can be
present in several scopes at once. On subscribe it receives:

1. `presence_state`, the full roster, once
2. `presence_join` / `presence_leave`, as it changes

Join and leave are broadcast to the whole scope, including the person who triggered
them, so a client can rely on a single code path instead of special-casing itself.

## Multiple tabs count once

Presence is keyed on the **member**, not the connection. One user with three tabs
produces one `presence_join`, and `presence_leave` only fires when their last
connection closes. That is handled by the store, not by the topic.

## Customise

```python
class DocumentPresenceTopic(PresenceTopic):
    def presence_member(self) -> PresenceMember:
        user = self.scope["user"]
        return PresenceMember(id=str(user.id), name=user.get_full_name(),
                              data={"avatar": user.avatar_url})
```

| Hook | Default | Purpose |
|---|---|---|
| `presence_member()` | authenticated user | Who is present |
| `presence_store` | `InMemoryPresenceStore()` | Where the roster lives |
| `announce_join/leave()` | broadcast to scope | Change or suppress announcements |

The scope itself is the topic parameter: a subscription to `presence:general` is
present in `general`.

## Production: replace the store

The default store is **process-local**. With more than one worker each process sees
only its own connections, so rosters come back incomplete. Use a shared store:

```bash
copit add @chanx-kit/redis-presence-store
```

```python
class SharedPresenceTopic(PresenceTopic):
    presence_store = RedisPresenceStore(Redis.from_url("redis://localhost:6379"))
```

Or implement the `PresenceStore` protocol against whatever you already run. It is
three methods.

## Query from anywhere

```python
members = await PresenceTopic.members_of("general")
```
