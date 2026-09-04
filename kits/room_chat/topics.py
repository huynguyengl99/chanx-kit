"""A chat room: replayable history, delivered live."""

from typing import ClassVar

from chanx.core.decorators import ws_handler
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage
from chanx.utils.scope import scope_user

from .messages import (
    ChatAuthor,
    ChatBacklogMessage,
    ChatBacklogPayload,
    ChatBacklogRequestMessage,
    ChatEntry,
    ChatMessage,
    ChatSendMessage,
)
from .store import InMemoryMessageStore, MessageStore


class RoomChatTopic(Topic[ChatMessage]):
    """Chat for one room: ``chat:<room>``.

    On subscribe the client receives ``chat_backlog`` with recent messages, then
    ``chat_message`` as they arrive. Replace :attr:`message_store` with a
    database-backed :class:`~.store.MessageStore`, because the in-memory default is not
    durable.
    """

    pattern = "chat:{room}"

    passthrough_events: ClassVar[list[type[BaseMessage]]] = [ChatMessage]

    message_store: ClassVar[MessageStore] = InMemoryMessageStore()
    backlog_limit: ClassVar[int] = 50

    @property
    def chat_room(self) -> str:
        return self.params["room"]

    def chat_author(self) -> ChatAuthor:
        """Who this connection posts as. Override to change identity."""
        user = scope_user(self.scope)
        if user is None:
            return ChatAuthor(id=self.channel_name, name="anonymous")
        identifier = getattr(user, "pk", None) or getattr(user, "id", None)
        return ChatAuthor(
            id=str(identifier or self.channel_name),
            name=str(getattr(user, "username", None) or identifier or "anonymous"),
        )

    async def on_subscribe(self) -> None:
        await self.send_message(await self.chat_backlog())

    async def chat_backlog(self, limit: int | None = None) -> ChatBacklogMessage:
        entries = await self.message_store.backlog(
            self.chat_room, limit or self.backlog_limit
        )
        return ChatBacklogMessage(
            payload=ChatBacklogPayload(room=self.chat_room, entries=entries)
        )

    @ws_handler(
        summary="Request history",
        description="Return recent messages again, without reconnecting.",
    )
    async def handle_chat_backlog_request(
        self, message: ChatBacklogRequestMessage
    ) -> ChatBacklogMessage:
        return await self.chat_backlog(message.payload.limit)

    @ws_handler(
        summary="Post a chat message",
        description="Persist a message and publish it to everyone in the room.",
        output_type=ChatMessage,
    )
    async def handle_chat_send(self, message: ChatSendMessage) -> None:
        await self.publish(
            ChatEntry(
                body=message.payload.body,
                author=self.chat_author(),
                room=self.chat_room,
            )
        )

    async def publish(self, entry: ChatEntry) -> None:
        """Persist first, publish second: an unsaved message is never shown as delivered."""
        await self.message_store.append(entry)
        await self.broadcast(self.topic, ChatMessage(payload=entry))

    @classmethod
    async def post_to_room(cls, room: str, body: str, author: ChatAuthor) -> ChatEntry:
        """Persist and deliver a message to ``room``, with no connection involved."""
        entry = ChatEntry(body=body, author=author, room=room)
        await cls.message_store.append(entry)
        await cls.broadcast(f"chat:{room}", ChatMessage(payload=entry))
        return entry

    @classmethod
    async def history(cls, room: str, limit: int = 50) -> list[ChatEntry]:
        """Recent messages for ``room``, callable from anywhere."""
        return await cls.message_store.backlog(room, limit)
