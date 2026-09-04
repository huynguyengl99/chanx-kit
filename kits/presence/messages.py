from typing import Any, Literal

from chanx.messages.base import BaseMessage
from pydantic import BaseModel, Field


class PresenceMember(BaseModel):
    """Someone present in a scope. ``id`` is what identifies them across connections."""

    id: str
    name: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class PresenceStatePayload(BaseModel):
    scope: str
    members: list[PresenceMember]


class PresenceEventPayload(BaseModel):
    scope: str
    member: PresenceMember


class PresenceStateMessage(BaseMessage):
    """Full member list, sent to a connection when it joins."""

    action: Literal["presence_state"] = "presence_state"
    payload: PresenceStatePayload


class PresenceJoinMessage(BaseMessage):
    """Someone became present in the scope."""

    action: Literal["presence_join"] = "presence_join"
    payload: PresenceEventPayload


class PresenceLeaveMessage(BaseMessage):
    """Someone is no longer present in the scope."""

    action: Literal["presence_leave"] = "presence_leave"
    payload: PresenceEventPayload


class PresenceRequestMessage(BaseMessage):
    """Client asks for the roster again, without reconnecting."""

    action: Literal["presence_request"] = "presence_request"
    payload: None = None
