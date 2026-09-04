import pytest
from fakeredis.aioredis import FakeRedis

from ...presence.messages import PresenceMember
from ...presence.store import PresenceStore
from ..store import RedisPresenceStore

ROOM = "general"
ANA = PresenceMember(id="ana", name="Ana")
BO = PresenceMember(id="bo", name="Bo")


@pytest.fixture
def store() -> RedisPresenceStore:
    return RedisPresenceStore(FakeRedis(), key_prefix="test:presence")


def test_satisfies_the_presence_store_protocol(store: RedisPresenceStore) -> None:
    assert isinstance(store, PresenceStore)


async def test_first_connection_makes_a_member_present(
    store: RedisPresenceStore,
) -> None:
    assert await store.add(ROOM, "conn-1", ANA) is True
    assert [m.id for m in await store.members(ROOM)] == ["ana"]


async def test_second_tab_does_not_report_a_new_arrival(
    store: RedisPresenceStore,
) -> None:
    await store.add(ROOM, "conn-1", ANA)

    assert await store.add(ROOM, "conn-2", ANA) is False
    assert [m.id for m in await store.members(ROOM)] == ["ana"]


async def test_leaving_reports_only_on_the_last_connection(
    store: RedisPresenceStore,
) -> None:
    await store.add(ROOM, "conn-1", ANA)
    await store.add(ROOM, "conn-2", ANA)

    assert await store.discard(ROOM, "conn-1") is None

    departed = await store.discard(ROOM, "conn-2")
    assert departed is not None
    assert departed.id == "ana"
    assert await store.members(ROOM) == []


async def test_discarding_an_unknown_connection_is_a_no_op(
    store: RedisPresenceStore,
) -> None:
    assert await store.discard(ROOM, "never-seen") is None


async def test_scopes_are_isolated(store: RedisPresenceStore) -> None:
    await store.add(ROOM, "conn-1", ANA)
    await store.add("other", "conn-2", BO)

    assert [m.id for m in await store.members(ROOM)] == ["ana"]
    assert [m.id for m in await store.members("other")] == ["bo"]


async def test_member_details_survive_the_round_trip(
    store: RedisPresenceStore,
) -> None:
    await store.add(ROOM, "conn-1", PresenceMember(id="ana", name="Ana", data={"a": 1}))

    (member,) = await store.members(ROOM)

    assert member.name == "Ana"
    assert member.data == {"a": 1}
