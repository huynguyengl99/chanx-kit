# chanx-testing

Backend-agnostic test harness for kit components: the same test suite runs against
**Django Channels** and **FastAPI / fast-channels**, so a kit proves it works on both
without being written twice.

```bash
copit add @chanx-kit/chanx-testing
```

You rarely install it directly. A kit whose copied tests use it declares it under its
`tests` optional group, so `copit add <kit> --with tests` brings it along, and an
install without the tests leaves it out.

## Use it

```python
from ..chanx_testing import (
    KitConsumer,
    build_app,
    communicator,
    receive_json,
    setup_memory_layer,
)


class RoomConsumer(KitConsumer):
    channel_layer_alias = "default"
    topics = [MyTopic]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")


async def test_something() -> None:
    app = build_app({"/ws/rooms/{room}": RoomConsumer})
    async with communicator(app, "/ws/rooms/{room}", RoomConsumer, room="general") as comm:
        (message,) = await receive_json(comm, 1)
```

Set `CHANX_KIT_BACKEND=channels` or `CHANX_KIT_BACKEND=fast_channels` to pin the
backend; otherwise whichever integration is importable is used.

## What it hides

The three things that actually differ between the backends:

| Helper | Hides |
|---|---|
| `KitConsumer` | which `AsyncJsonWebsocketConsumer` to subclass |
| `build_app(routes)` | route declaration, where `{name}` captures work on both |
| `setup_memory_layer(alias)` | how an in-memory channel layer is registered |
| `communicator(app, path, consumer, **params)` | which test communicator to open |

## Reading messages

Read an **expected number** of messages, never "drain until timeout": asgiref's test
communicator cancels the running application on a read timeout, so the first timeout
silently kills the connection and every later read comes back empty.

| Helper | Purpose |
|---|---|
| `receive_json(comm, n)` | read exactly `n` messages |
| `receive_until(comm, action)` | skip ahead to one action |
| `assert_silent(comm)` | assert nothing further arrives; polls, no timeout kill |
