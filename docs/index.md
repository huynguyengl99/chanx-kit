---
hide:
  - navigation
---

# ChanX Kit

*Pronounced "chan-X kit": a collection of composable, copy-in WebSocket kits for
[chanx](https://github.com/huynguyengl99/chanx) (**CHAN**nels-e**X**tension).*

Instead of installing a framework that owns your consumers, you copy a kit into your
project and own it. No hidden abstractions, no dependency you cannot inspect, and an
install footprint that is exactly what you used.

<div class="grid cards" markdown>

-   :material-download: **Copy, don't install**

    ---

    `copit add @chanx-kit/notification` drops readable source into your project.
    Edit it, delete half of it, rename things. It's yours.

-   :material-language-typescript: **Typed end to end**

    ---

    pyright strict with no suppressions, and TypeScript types generated from the
    server's own AsyncAPI schema.

-   :material-swap-horizontal: **Django *and* FastAPI**

    ---

    Kits import only `chanx.core`, so one component runs on Channels and
    fast-channels. Every kit's tests run on both in CI.

-   :material-puzzle: **Composable**

    ---

    Stack as many kits into one consumer as you like, with no type errors and no
    `# pyright: ignore`.

</div>

## In one minute

```bash
copit add @chanx-kit/notification
```

```python
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

from .ws_kits.notification import NotificationMessage, UserNotificationTopic


class AppConsumer(AsyncJsonWebsocketConsumer[NotificationMessage]):
    channel_layer_alias = "default"
    topics = [UserNotificationTopic]
```

Then, from a signal, a worker, or another service, with the consumer never imported:

```python
await UserNotificationTopic.notify_user(
    user.id, NotificationPayload(title="Build finished")
)
```

[Browse the kits](kits/index.md){ .md-button .md-button--primary }
[Getting started](getting-started.md){ .md-button }
