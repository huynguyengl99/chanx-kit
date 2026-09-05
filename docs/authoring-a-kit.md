# Authoring a kit

A kit is a topic and a message module. This page is the how-to; [Questions](questions.md)
covers why the shape is what it is.

## The shape

```
kits/<package_name>/
  kit.yaml               # registry metadata
  messages.py            # the wire contract
  topics.py              # the kit's Topic classes: handlers, auth, broadcasting
  store.py               # pluggable persistence (optional)
  README.md
  tests/
```

The directory name is the Python package a user imports, so it must be a valid
identifier: `room_chat`, while the registry id in `kit.yaml` uses dashes
(`room-chat`). CI checks the two agree.

## Topics are listed, not inherited

```python
class AppConsumer(AsyncJsonWebsocketConsumer[AppEvents]):
    topics = [UserNotificationTopic, RoomChatTopic, PresenceTopic]
```

Listing them is what lets any number of kits compose: their event types never meet, and
each keeps its own handler namespace and its own `authorize`. The mixin you might reach
for first cannot do this, and [Questions](questions.md) has the type error it produces.

## Rules for kit code

**Import only framework-agnostic chanx.** Never `chanx.channels` or
`chanx.fast_channels`, which would pin the kit to one framework. `chanx.utils.scope`
covers what the frameworks disagree about, such as URL captures, and a topic resolves
its own channel layer.

The exception is a kit that declares `only_variants` in its `kit.yaml`, which is
how a kit says it targets one framework on purpose. It is then excluded from the other
backend's test run, so it may import that framework freely. Reach for it only when
porting is impossible: models and migrations, not convenience. See
[our registry conventions](registry-conventions.md).

**Put per-subscriber setup in `on_subscribe`.** It runs once the group is joined, with
the request's ref cleared so state you push is not mistaken for a reply. Clean up in
`on_unsubscribe`, which runs on both an explicit unsubscribe and a disconnect.

**Namespace your pattern.** A topic string is a global namespace shared by every
consumer in a user's project, so prefix it: `notification:user:{user_id}`, not
`{user_id}`. Group names are derived from it and kept backend-safe automatically.

**Broadcasts must come from the class the consumer mounts.** A group name carries the
topic's class name, so once a user subclasses your kit, outside code has to publish
through *their* subclass. Say so next to any publishing classmethod you offer, because
getting it wrong is silent. See [Questions](questions.md).

**Make persistence pluggable.** Ship a `Protocol` plus an in-memory default, and say
plainly in the README that the default is not durable or multi-worker safe. Users
replace it; they should not have to fork your kit to do so.

## Tests

Tests use the [`chanx-testing`](kits/chanx-testing.md) kit so one suite runs against
both backends. Declare it under your kit's `tests` optional group (see
[Dependencies](#dependencies)), and import it relatively:

```python
class RoomConsumer(KitConsumer):
    channel_layer_alias = "default"
    topics = [MyTopic]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")


async def test_something(app: Any) -> None:
    async with communicator(app, PATH, RoomConsumer) as comm:
        (message,) = await receive_json(comm, 1)
```

**Read an expected number of messages.** Do not drain until a timeout. asgiref's test
communicator cancels the running application whenever a read times out, so the first
timeout kills the connection and every later read comes back empty, which looks
exactly like a broadcast that never arrived. `chanx.core.testing.receive_all_json()`
does this internally, so it is unsafe in any test that reads more than once.

Use `receive_json(comm, n)` to read, `receive_until(comm, action)` to skip ahead, and
`assert_silent(comm)` to assert nothing arrives, since it polls instead of timing out.

### Assert on what was published, not only on what arrived

Checking a broadcast by opening a second client conflates two failures: the wrong topic
and a broken delivery path look identical. `chanx.core.testing.capture_topic_broadcasts`
records the publish side, the topic each event was addressed to:

```python
with capture_topic_broadcasts(PresenceTopic, suppress=False) as broadcasts:
    await comm.subscribe("presence:general")
    state, delivered = await receive_json(comm, 2)

assert broadcasts[0].topic == "presence:general"
assert broadcasts[0].event.action == "presence_join"
```

It patches the topic's `broadcast` classmethod, so it works on any kit unchanged.

Prefer `suppress=False`. Suppressing stops delivery, which means the connection never
sees the message *and* the assertion can run before the consumer has reached the
publishing line, a race that reads as an empty capture list. Keeping delivery on and
reading the delivered message proves the broadcast already happened.

### Test the real path, not only a stubbed one

Kits give users override points such as `run_agent`, `presence_store` and
`message_store`. Make
sure *something* still exercises the default. A suite that always substitutes a stub
proves the kit's own logic and nothing about the code most users run: rename an upstream
method and it still passes.

If the kit wraps a library, prefer that library's own test double (pydantic-ai's
`FunctionModel`, say) over mocking HTTP: no API key, no network, but the real pipeline.
Fall back to intercepting the transport (`respx`) only when there isn't one.

Worth confirming such a test can fail: break the call on purpose and check it goes red.

## The wire contract

A kit's messages are its public API: once someone copies the kit into production and
ships a frontend against it, changing a payload breaks them.

That contract is frozen by the **generated TypeScript types**, which CI regenerates from
the sandbox's AsyncAPI schema and diffs. A payload change therefore shows up as a
reviewable TS diff, and the author has to regenerate:

```bash
npm --prefix sandbox/ui run gen
```

This is why a new kit must be mounted in `sandbox/consumers.py`: a kit nobody mounts is
absent from that schema and has no contract check at all. A test enforces it.

## Dependencies

```yaml
requires:
  - presence            # another kit; resolved transitively at install time
dependencies:
  - "chanx>=2.10.0,<3"  # package deps, installed via the user's package manager

optional:
  tests:
    requires:
      - chanx-testing   # only for someone who installs with --with tests
```

Import a required kit with a relative import, `from ..presence.store import
PresenceStore`. Kits sit side by side both in this repo and in a user's project, so the
same import works in both.

`requires` is what *every* install of your kit copies, so put the harness under the
`tests` group instead: a user who never asked for tests should not receive a test
harness. copit resolves a group's requirement only when that group is selected.

`core` kits may only depend on `core`. `contrib` may depend on either. CI enforces it,
along with id uniqueness and the absence of dependency cycles. See
[our registry conventions](registry-conventions.md) for why the layout is flat.
