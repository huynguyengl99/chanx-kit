"""WebSocket consumers. After ``copit add``, list the kit's topics here."""

from typing import Any, ClassVar

from chanx.core.decorators import channel, ws_handler
from chanx.core.topic import Topic
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from chanx.messages.incoming import PingMessage
from chanx.messages.outgoing import PongMessage
from chanx.utils.scope import query_params

from app.layers import ALIAS
from app.ws_kits.notification import (
    BroadcastNotificationTopic,
    NotificationMessage,
    UserNotificationTopic,
)


# Demo identity from ``?as=<name>``; replace with your auth.
class AppUserNotificationTopic(UserNotificationTopic):
    """Notifications for one user: ``notification:user:<user_id>``."""

    def current_user_id(self) -> str | None:
        return query_params(self.scope).get("as", [""])[0] or None


@channel(
    name="notifications",
    description="Notifications for the connected user, and for everyone.",
    tags=["notification"],
)
class NotificationConsumer(AsyncJsonWebsocketConsumer[NotificationMessage]):
    channel_layer_alias = ALIAS
    topics: ClassVar[list[type[Topic[Any]]]] = [
        AppUserNotificationTopic,
        BroadcastNotificationTopic,
    ]

    @ws_handler(summary="Ping", description="Connection health check.")
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()
