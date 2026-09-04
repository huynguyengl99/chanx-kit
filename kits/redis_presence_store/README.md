# redis-presence-store

Shared presence roster backed by Redis, so presence stays correct across multiple
workers.

```bash
copit add @chanx-kit/redis-presence-store   # also installs: presence
```

## Why

The `presence` kit defaults to `InMemoryPresenceStore`, which keeps the roster in the
worker process. Run two workers and each one reports only the connections it happens to
hold, so clients see a roster that is missing people. This store puts that state in
Redis instead.

## Use it

```python
from redis.asyncio import Redis

from .ws_kits.presence import PresenceTopic
from .ws_kits.redis_presence_store import RedisPresenceStore


class SharedPresenceTopic(PresenceTopic):
    presence_store = RedisPresenceStore(Redis.from_url("redis://localhost:6379"))
```

Nothing else changes: it satisfies the same `PresenceStore` protocol.

## How state is kept

One Redis hash per scope, mapping connection id to the member JSON. Membership is
*derived* from that hash rather than tracked in a separate counter, so a worker that
dies mid-connection cannot corrupt a count and leave someone permanently "online".

Each write refreshes a TTL (default one hour) on the hash, so a scope abandoned by a
crashed worker expires instead of lingering forever.

```python
RedisPresenceStore(redis, key_prefix="myapp:presence", ttl=1800)
```

## Trade-offs

- Every join and leave costs a round trip; `members()` costs one `HGETALL`. For very
  large scopes, page the roster instead of sending it whole.
- The TTL is a backstop, not a heartbeat. If you need sub-hour accuracy for crashed
  workers, lower `ttl` and re-register connections periodically.
- `add()` and `discard()` read then write without a transaction, so one member's tabs
  churning across workers at the same instant can duplicate or skip a join/leave
  announcement. The roster itself self-heals on the next read. If announcements must
  be exact, make the membership check atomic with a Lua script.
