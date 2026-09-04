from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from chanx.messages.base import BaseMessage
from pydantic import BaseModel, Field


class NotificationLevel(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class NotificationPayload(BaseModel):
    title: str
    body: str | None = None
    level: NotificationLevel = NotificationLevel.INFO
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class NotificationMessage(BaseMessage):
    """A notification delivered to the client."""

    action: Literal["notification"] = "notification"
    payload: NotificationPayload


class NotificationAckPayload(BaseModel):
    ids: list[str]


class NotificationAckMessage(BaseMessage):
    """Client acknowledges that notifications were seen."""

    action: Literal["notification_ack"] = "notification_ack"
    payload: NotificationAckPayload


class NotificationAckedMessage(BaseMessage):
    """Server confirms an acknowledgement was recorded."""

    action: Literal["notification_acked"] = "notification_acked"
    payload: NotificationAckPayload
