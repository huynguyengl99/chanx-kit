from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from chanx.messages.base import BaseMessage
from pydantic import BaseModel, Field


class ChatAuthor(BaseModel):
    id: str
    name: str | None = None


class ChatEntry(BaseModel):
    """One persisted chat message."""

    body: str
    author: ChatAuthor
    room: str
    id: str = Field(default_factory=lambda: uuid4().hex)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatSendPayload(BaseModel):
    body: str


class ChatSendMessage(BaseMessage):
    """Client posts a message to the room."""

    action: Literal["chat_send"] = "chat_send"
    payload: ChatSendPayload


class ChatMessage(BaseMessage):
    """A message published to the room."""

    action: Literal["chat_message"] = "chat_message"
    payload: ChatEntry


class ChatBacklogPayload(BaseModel):
    room: str
    entries: list[ChatEntry]


class ChatBacklogMessage(BaseMessage):
    """Recent history, sent to a connection when it joins."""

    action: Literal["chat_backlog"] = "chat_backlog"
    payload: ChatBacklogPayload


class ChatBacklogRequestPayload(BaseModel):
    limit: int | None = None


class ChatBacklogRequestMessage(BaseMessage):
    """Client asks for history again, without reconnecting."""

    action: Literal["chat_backlog_request"] = "chat_backlog_request"
    payload: ChatBacklogRequestPayload = ChatBacklogRequestPayload()
