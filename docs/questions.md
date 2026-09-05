# Questions

The reasoning behind the shapes the kits take. None of this is needed to *use* a kit,
but it is what stops the obvious alternatives being retried.

## Why a topic, and not a mixin?

A kit has two jobs: it adds handlers to a connection, and it lets code with no
connection push events to clients. The natural first attempt is a mixin parametrised
with the kit's events:

```python
class NotificationMixin(ChanxWebsocketConsumerMixin[NotificationMessage]):   # DON'T
    ...
```

That reads well until someone composes two kits, because both parametrise the same
base differently:

```
error: Base classes of AppConsumer are mutually incompatible
  Base class "ChanxWebsocketConsumerMixin[NotifyEvent | ChatEvent]" derives from
  ...which is incompatible with type "ChanxWebsocketConsumerMixin[NotifyEvent]"
```

Composing kits is the entire point of a registry, so the shape has to survive it.
A topic does, because topics are **listed** on a consumer rather than inherited:

```python
class AppConsumer(AsyncJsonWebsocketConsumer[AppEvents]):
    topics = [UserNotificationTopic, RoomChatTopic, PresenceTopic]
```

Their event types never meet, so any number compose. Each topic keeps its own handler
namespace too, so two kits may both define a `cancel` action without colliding, and its
own `authorize`, so one kit cannot widen another's access.

```python
class UserNotificationTopic(Topic[NotificationMessage]):
    pattern = "notification:user:{user_id}"
    passthrough_events: ClassVar[list[type[BaseMessage]]] = [NotificationMessage]

    async def authorize(self, **params: str) -> bool:
        return self.current_user_id() == params["user_id"]
```

## What does a topic give me?

- `UserNotificationTopic.broadcast(topic, event)` reaches every subscriber, from a
  signal or worker, with no consumer imported and nothing to bind.
- `AppConsumer.broadcast_event(event)` stays typed to the consumer's own union.
- Any number of kits compose with no suppressions, and each works alone.
- A topic can also serve a dedicated route with `as_consumer()`, where connecting is
  the subscription and clients send no envelope.

## Why must a broadcast come from the class the consumer mounts?

A group name is derived from the topic string *and* the topic's class name. So
`MyNotificationTopic` and the `UserNotificationTopic` it subclasses address different
groups, even for the same topic string:

```python
UserNotificationTopic.group_name("notification:user:42")
# UserNotificationTopic.notification-user-42
MyNotificationTopic.group_name("notification:user:42")
# MyNotificationTopic.notification-user-42
```

The namespace is what keeps two unrelated topic classes from colliding once unsupported
characters are replaced. The cost is that as soon as you override a hook, code outside
the connection has to publish through *your* subclass.

Getting it wrong is silent, because a broadcast to a group nobody joined is not an
error. If a worker's events never arrive, check this first.

## Why is `tier` metadata rather than a directory?

So promotion is a one-line change, and because copit installs kits side by side into
one directory: nesting them under `core/` and `contrib/` here would make a cross-kit
import need a different depth than it does in a user's project. See
[our registry](registry-conventions.md).

## Why does the test harness arrive only with `--with tests`?

Because a user who did not ask for tests should not receive a test harness. Kits
declare `chanx-testing` under their `tests` optional group rather than in `requires`,
and copit resolves a group's requirements only when that group is selected. See
[our registry](registry-conventions.md).
