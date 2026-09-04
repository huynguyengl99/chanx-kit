from typing import Any, ClassVar

import pytest
from chanx.core.topic import Topic
from chanx.utils.scope import query_params

from ...chanx_testing import (
    KitConsumer,
    assert_silent,
    build_app,
    communicator,
    receive_json,
    setup_memory_layer,
)
from ..messages import PresenceMember, PresenceRequestMessage
from ..store import InMemoryPresenceStore
from ..topics import PresenceTopic

PATH = "/ws/presence"
ROOM = "general"
TOPIC = f"presence:{ROOM}"

store = InMemoryPresenceStore()


class MemberPresenceTopic(PresenceTopic):
    """Identity comes from the query string so tests can control who connects."""

    presence_store: ClassVar[Any] = store

    def presence_member(self) -> PresenceMember:
        member_id = query_params(self.scope).get("as", ["anonymous"])[0]
        return PresenceMember(id=member_id, name=member_id.title())


class RoomConsumer(KitConsumer):
    channel_layer_alias = "default"
    topics: ClassVar[list[type[Topic[Any]]]] = [MemberPresenceTopic]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")
    store.clear()


@pytest.fixture
def app() -> Any:
    return build_app({PATH: RoomConsumer})


def connect(app: Any, member: str) -> Any:
    return communicator(app, f"{PATH}?as={member}", RoomConsumer)


async def join(app: Any, member: str) -> Any:
    """Connect, subscribe, and consume the state and own join."""
    comm = connect(app, member)
    await comm.connect()
    await comm.subscribe(TOPIC)
    await receive_json(comm, 2)
    return comm


async def test_joining_connection_receives_the_current_roster(app: Any) -> None:
    first = await join(app, "ana")
    second = connect(app, "bo")
    await second.connect()
    await second.subscribe(TOPIC)

    state, own_join = await receive_json(second, 2)

    assert state["action"] == "presence_state"
    assert state["payload"]["scope"] == ROOM
    assert sorted(m["id"] for m in state["payload"]["members"]) == ["ana", "bo"]
    assert own_join["payload"]["member"]["id"] == "bo"
    # state is pushed by on_subscribe, so it is not a reply to the request
    assert "ref" not in state

    await second.disconnect()
    await first.disconnect()


async def test_existing_members_are_told_about_a_join(app: Any) -> None:
    first = await join(app, "ana")
    second = await join(app, "bo")

    (notice,) = await receive_json(first, 1)

    assert notice["action"] == "presence_join"
    assert notice["payload"]["member"]["id"] == "bo"
    assert notice["payload"]["member"]["name"] == "Bo"
    assert notice["topic"] == TOPIC

    await second.disconnect()
    await first.disconnect()


async def test_leaving_is_announced(app: Any) -> None:
    first = await join(app, "ana")
    second = await join(app, "bo")
    await receive_json(first, 1)

    await second.disconnect()
    (notice,) = await receive_json(first, 1)

    assert notice["action"] == "presence_leave"
    assert notice["payload"]["member"]["id"] == "bo"

    await first.disconnect()


async def test_unsubscribing_announces_a_leave(app: Any) -> None:
    """Leaving a scope no longer requires dropping the connection."""
    first = await join(app, "ana")
    second = await join(app, "bo")
    await receive_json(first, 1)

    await second.unsubscribe(TOPIC, ref="9")
    (notice,) = await receive_json(first, 1)

    assert notice["action"] == "presence_leave"
    assert notice["payload"]["member"]["id"] == "bo"

    await second.disconnect()
    await first.disconnect()


async def test_a_second_tab_does_not_produce_a_second_join(app: Any) -> None:
    first = await join(app, "ana")
    tab_one = await join(app, "bo")
    await receive_json(first, 1)

    tab_two = connect(app, "bo")
    await tab_two.connect()
    await tab_two.subscribe(TOPIC)
    await receive_json(tab_two, 1)  # state only, no join is announced

    await assert_silent(first)

    await tab_two.disconnect()
    await tab_one.disconnect()
    await first.disconnect()


async def test_leave_is_announced_only_when_the_last_tab_closes(app: Any) -> None:
    first = await join(app, "ana")
    tab_one = await join(app, "bo")
    await receive_json(first, 1)

    tab_two = connect(app, "bo")
    await tab_two.connect()
    await tab_two.subscribe(TOPIC)
    await receive_json(tab_two, 1)

    await tab_two.disconnect()
    await assert_silent(first)

    await tab_one.disconnect()
    (notice,) = await receive_json(first, 1)

    assert notice["action"] == "presence_leave"
    assert notice["payload"]["member"]["id"] == "bo"

    await first.disconnect()


async def test_members_of_is_callable_without_a_connection(app: Any) -> None:
    first = await join(app, "ana")

    members = await MemberPresenceTopic.members_of(ROOM)

    assert [m.id for m in members] == ["ana"]
    await first.disconnect()


async def test_roster_is_emptied_once_everyone_leaves(app: Any) -> None:
    first = await join(app, "ana")
    await first.disconnect()

    assert await MemberPresenceTopic.members_of(ROOM) == []


async def test_roster_can_be_requested_without_reconnecting(app: Any) -> None:
    first = await join(app, "ana")
    second = await join(app, "bo")
    await receive_json(first, 1)

    await first.send_message(PresenceRequestMessage(), topic=TOPIC, ref="7")
    (state,) = await receive_json(first, 1)

    assert state["action"] == "presence_state"
    assert sorted(m["id"] for m in state["payload"]["members"]) == ["ana", "bo"]
    # this one *is* a reply, so it carries the request's ref
    assert state["ref"] == "7"

    await second.disconnect()
    await first.disconnect()


async def test_one_connection_can_be_present_in_several_scopes(app: Any) -> None:
    """The scope is a topic parameter, not the URL, so scopes are joined at runtime."""
    comm = connect(app, "ana")
    await comm.connect()
    await comm.subscribe("presence:general")
    await receive_json(comm, 2)
    await comm.subscribe("presence:random", ref="2")
    await receive_json(comm, 2)

    assert [m.id for m in await MemberPresenceTopic.members_of("general")] == ["ana"]
    assert [m.id for m in await MemberPresenceTopic.members_of("random")] == ["ana"]

    await comm.disconnect()


def test_each_scope_gets_its_own_group() -> None:
    general = MemberPresenceTopic.group_name("presence:general")
    random = MemberPresenceTopic.group_name("presence:random")

    assert general != random
