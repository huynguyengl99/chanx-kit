# Getting started

## Install chanx

Nothing is installed from this registry: kits are copied in. The only package they
need is chanx itself, with the integration you use:

=== "FastAPI"

    ```bash
    pip install "chanx[fast_channels]"
    ```

=== "Django"

    ```bash
    pip install "chanx[channels]"
    ```

## Add a kit

Kits are copied with [copit](https://github.com/huynguyengl99/copit). copit has no
built-in list of registries, so you tell it about this one once and it remembers in
`copit.toml`:

```bash
uvx copit init
uvx copit registry add chanx-kit github:huynguyengl99/chanx-kit@v0.1.0 --to app/ws_kits
```

That records where the registry lives, where kits should land, and pins the version:

```toml
[registries.chanx-kit]
source = "github:huynguyengl99/chanx-kit@v0.1.0"
target = "app/ws_kits"
```

After that, install by name:

```bash
uvx copit add @chanx-kit/notification
```

This drops the kit's source into your project (messages, topics and any store helpers),
installs any Python packages it declares, and pulls in any kit it requires.

!!! tip "Useful flags"
    `--dry-run` shows the plan without writing. `-y` skips the confirmation.
    `--with tests` also copies the kit's tests, which is worth it if you plan to modify
    it. `--variant django` or `--variant fastapi` selects framework-specific files.

Later, to pick up upstream fixes:

```bash
uvx copit update app/ws_kits/notification            # same pinned version
uvx copit update app/ws_kits/notification --ref v0.2.0
```

Files you have edited are preserved if you list them in `excludes` in `copit.toml`.

## Mount it on a consumer

A kit is a **topic**: a pattern clients address, with its own handlers, authorization
and group. List it on a consumer:

```python
class AppConsumer(AsyncJsonWebsocketConsumer[NotificationMessage]):
    channel_layer_alias = "default"
    topics = [UserNotificationTopic]
```

Add the kit's messages to the consumer's event union so it can deliver them. List as
many kits as you need. They are independent, so this one consumer serves chat history
*and* a live roster, and either would work without the other:

```python
class RoomConsumer(
    AsyncJsonWebsocketConsumer[
        ChatMessage | PresenceJoinMessage | PresenceLeaveMessage
    ],
):
    channel_layer_alias = "default"
    topics = [RoomChatTopic, PresenceTopic]
```

Clients then address a topic per frame, and subscribe to the ones they want:

```json
{"version": 1, "topic": "chat:general", "ref": "1", "action": "subscribe"}
```

## Broadcast from outside a connection

A topic reaches the channel layer itself, so a signal or worker can push to connected
clients without importing a consumer:

```python
await UserNotificationTopic.notify_user(
    user.id, NotificationPayload(title="Build finished")
)
```

!!! warning "Broadcasting across processes needs a shared channel layer"
    An in-memory layer lives inside one process, so a worker publishing into its own
    layer will never reach the browser. Use Redis for anything multi-process.

## Customise it

Everything is an ordinary method, so subclass and override:

```python
class TenantNotificationTopic(UserNotificationTopic):
    def current_user_id(self) -> str | None:
        tenant = dict(self.scope["headers"]).get(b"x-tenant-id")
        return tenant.decode() if tenant else None

    async def on_notifications_acked(self, ids: list[str]) -> None:
        await Notification.objects.filter(id__in=ids).aupdate(read=True)
```

Each kit's page lists its hooks and their defaults.

## Next

- [Browse the kits](kits/index.md)
- [Authoring a kit](authoring-a-kit.md): what a topic is made of, and why
