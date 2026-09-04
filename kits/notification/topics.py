"""Notification streams, one topic per audience."""

from typing import ClassVar

from chanx.core.decorators import ws_handler
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage
from chanx.utils.scope import scope_user

from .messages import (
    NotificationAckedMessage,
    NotificationAckMessage,
    NotificationMessage,
    NotificationPayload,
)


class NotificationTopicBase(Topic[NotificationMessage]):
    """Shared behaviour for every notification stream. Override
    :meth:`on_notifications_acked` to persist read state."""

    passthrough_events: ClassVar[list[type[BaseMessage]]] = [NotificationMessage]

    async def on_notifications_acked(self, ids: list[str]) -> None:
        """Record that the client saw these notifications. No-op by default."""

    @ws_handler(
        summary="Acknowledge notifications",
        description="Mark one or more delivered notifications as seen.",
    )
    async def handle_notification_ack(
        self, message: NotificationAckMessage
    ) -> NotificationAckedMessage:
        await self.on_notifications_acked(message.payload.ids)
        return NotificationAckedMessage(payload=message.payload)

    @classmethod
    async def notify(cls, topic: str, notification: NotificationPayload) -> None:
        """Send a notification to everyone subscribed to ``topic``."""
        await cls.broadcast(topic, NotificationMessage(payload=notification))


class UserNotificationTopic(NotificationTopicBase):
    """Notifications addressed to one user: ``notification:user:<user_id>``."""

    pattern = "notification:user:{user_id}"

    async def authorize(self, **params: str) -> bool:
        """Only the user themselves may listen to their own notifications."""
        return self.current_user_id() == params["user_id"]

    def current_user_id(self) -> str | None:
        """This connection's user id. Override when identity lives elsewhere."""
        user = scope_user(self.scope)
        if user is None:
            return None
        identifier = getattr(user, "pk", None) or getattr(user, "id", None)
        return None if identifier is None else str(identifier)

    @classmethod
    async def notify_user(
        cls, user_id: object, notification: NotificationPayload
    ) -> None:
        """Send a notification to every live connection of one user."""
        await cls.notify(f"notification:user:{user_id}", notification)


class SubjectNotificationTopic(NotificationTopicBase):
    """Notifications for a subject users opt into: ``notification:subject:<name>``."""

    pattern = "notification:subject:{subject}"

    @classmethod
    async def notify_subject(
        cls, subject: str, notification: NotificationPayload
    ) -> None:
        """Send a notification to everyone subscribed to ``subject``."""
        await cls.notify(f"notification:subject:{subject}", notification)


class BroadcastNotificationTopic(NotificationTopicBase):
    """Notifications addressed to everyone: ``notification:all``."""

    pattern = "notification:all"

    @classmethod
    async def notify_all(cls, notification: NotificationPayload) -> None:
        """Send a notification to every subscribed client."""
        await cls.notify("notification:all", notification)
