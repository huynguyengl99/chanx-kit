# notification

Fan out notifications to a user's live connections from anywhere in your app: a
Django signal, a background worker, another service.

```bash
copit add @chanx-kit/notification
```

## Use it

List the topics on a consumer and add `NotificationMessage` to its event union:

```python
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

from .ws_kits.notification import (
    BroadcastNotificationTopic,
    NotificationMessage,
    UserNotificationTopic,
)


class AppConsumer(AsyncJsonWebsocketConsumer[NotificationMessage]):
    channel_layer_alias = "default"
    topics = [UserNotificationTopic, BroadcastNotificationTopic]
```

A client subscribes to the audiences it wants (`notification:user:<id>`,
`notification:subject:<name>`, `notification:all`), and `authorize` decides per
subscription: asking for another user's notifications is refused.

## Send a notification

From anywhere, with the consumer never imported:

```python
from .ws_kits.notification import NotificationPayload, UserNotificationTopic

await UserNotificationTopic.notify_user(
    user.id, NotificationPayload(title="Build finished", level="success")
)
await BroadcastNotificationTopic.notify_all(NotificationPayload(title="Maintenance at 22:00"))
```

From a Django signal, or any other sync context:

```python
@receiver(post_save, sender=Invoice)
def invoice_saved(instance, created, **kwargs):
    async_to_sync(UserNotificationTopic.notify_user)(
        instance.owner_id, NotificationPayload(title="Order shipped")
    )
```

## Customise

Everything is an ordinary method, so subclass and override:

```python
class TenantNotificationTopic(UserNotificationTopic):
    def current_user_id(self) -> str | None:
        tenant = dict(self.scope["headers"]).get(b"x-tenant-id")
        return tenant.decode() if tenant else None

    async def on_notifications_acked(self, ids: list[str]) -> None:
        await Notification.objects.filter(id__in=ids).aupdate(read=True)
```

| Hook | Default | Purpose |
|---|---|---|
| `current_user_id()` | authenticated user's pk | Identify whose notifications this connection gets |
| `authorize(**params)` | user id must match | Who may subscribe to an audience |
| `on_notifications_acked(ids)` | no-op | Persist read state |

## Messages

| Action | Direction | Payload |
|---|---|---|
| `notification` | server → client | `title`, `body`, `level`, `id`, `created_at`, `data` |
| `notification_ack` | client → server | `ids` |
| `notification_acked` | server → client | `ids` |
