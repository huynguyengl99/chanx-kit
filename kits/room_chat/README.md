# room-chat

A chat room: persisted history replayed on connect, plus a live roster.

```bash
copit add @chanx-kit/room-chat   # installs presence too
```

## Use it

List the topic on a consumer and add `ChatMessage` to its event union:

```python
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

from .ws_kits.room_chat import RoomChatTopic, ChatMessage


class RoomConsumer(AsyncJsonWebsocketConsumer[ChatMessage]):
    channel_layer_alias = "default"
    topics = [RoomChatTopic]
```

A client subscribes to `chat:<room>` and receives `chat_backlog` with recent history,
then `chat_message` for anything posted afterwards.

Posting persists **before** it publishes, so a message that fails to save is never
shown to anyone as delivered.

## The roster comes with it

This kit installs `presence` alongside it. List both topics on the consumer and a
client can subscribe to `chat:<room>` and `presence:<room>` on the same connection.
Each kit keeps its own handlers, and either works alone.

## Post without a connection

```python
await RoomChatTopic.post_to_room(
    "general", "deploy finished", ChatAuthor(id="bot", name="CI")
)
entries = await RoomChatTopic.history("general", limit=20)
```

## Customise

| Hook | Default | Purpose |
|---|---|---|
| `chat_author()` | authenticated user | Who the connection posts as |
| `message_store` | `InMemoryMessageStore()` | Where history lives |
| `backlog_limit` | `50` | How much history a joiner gets |
| `publish(entry)` | persist + broadcast | Hook moderation, rate limits, fan-out |

The room itself is the topic parameter: a subscription to `chat:general` is in room
`general`, and one connection can be in several rooms at once.

## Production: replace the store

`InMemoryMessageStore` is bounded and per-process, so history is lost on restart and
differs between workers. Implement `MessageStore` against your database:

```python
class DjangoMessageStore(MessageStore):
    async def append(self, entry: ChatEntry) -> None:
        await Message.objects.acreate(**entry.model_dump())

    async def backlog(self, room: str, limit: int) -> list[ChatEntry]:
        rows = Message.objects.filter(room=room).order_by("-sent_at")[:limit]
        return [ChatEntry.model_validate(row, from_attributes=True) async for row in rows][::-1]
```

## Messages

| Action | Direction | Payload |
|---|---|---|
| `chat_send` | client → server | `body` |
| `chat_message` | server → client | `id`, `body`, `author`, `room`, `sent_at` |
| `chat_backlog` | server → client | `room`, `entries` |
