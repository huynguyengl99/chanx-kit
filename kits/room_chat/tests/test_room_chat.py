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
from ...presence.messages import PresenceMember
from ...presence.store import InMemoryPresenceStore
from ...presence.topics import PresenceTopic
from ..messages import (
    ChatAuthor,
    ChatBacklogRequestMessage,
    ChatBacklogRequestPayload,
    ChatSendMessage,
    ChatSendPayload,
)
from ..store import InMemoryMessageStore
from ..topics import RoomChatTopic

PATH = "/ws/rooms"
ROOM = "general"
CHAT = f"chat:{ROOM}"
PRESENCE = f"presence:{ROOM}"

store = InMemoryMessageStore()
roster = InMemoryPresenceStore()


def _who(scope: Any) -> str:
    return query_params(scope).get("as", ["anonymous"])[0]


class ChatTopicForTests(RoomChatTopic):
    message_store: ClassVar[Any] = store

    def chat_author(self) -> ChatAuthor:
        who = _who(self.scope)
        return ChatAuthor(id=who, name=who.title())


class PresenceTopicForTests(PresenceTopic):
    presence_store: ClassVar[Any] = roster

    def presence_member(self) -> PresenceMember:
        who = _who(self.scope)
        return PresenceMember(id=who, name=who.title())


class RoomConsumer(KitConsumer):
    """Chat and presence are listed side by side, not stacked by inheritance."""

    channel_layer_alias = "default"
    topics: ClassVar[list[type[Topic[Any]]]] = [
        ChatTopicForTests,
        PresenceTopicForTests,
    ]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")
    store.clear()
    roster.clear()


@pytest.fixture
def app() -> Any:
    return build_app({PATH: RoomConsumer})


async def join(app: Any, who: str, room: str = ROOM) -> tuple[Any, dict[str, Any]]:
    """Connect, subscribe to both topics, and drain the opening messages."""
    comm = communicator(app, f"{PATH}?as={who}", RoomConsumer)
    await comm.connect()
    for ref, topic in enumerate((f"chat:{room}", f"presence:{room}"), start=1):
        await comm.send_json_to(
            {"version": 1, "topic": topic, "ref": str(ref), "action": "subscribe"}
        )

    # two confirmations, plus chat_backlog, presence_state and presence_join
    received = await receive_json(comm, 5)
    return comm, {
        message["action"]: message
        for message in received
        if message["action"] != "subscribed"
    }


async def test_subscribing_gives_both_the_roster_and_the_history(app: Any) -> None:
    """Two independent kits on one connection, each sending its own opening state."""
    comm, opening = await join(app, "ana")

    assert set(opening) == {"presence_state", "presence_join", "chat_backlog"}
    assert opening["chat_backlog"]["payload"]["entries"] == []
    assert [m["id"] for m in opening["presence_state"]["payload"]["members"]] == ["ana"]

    await comm.disconnect()


async def test_each_kit_keeps_its_own_topic(app: Any) -> None:
    comm, opening = await join(app, "ana")

    assert opening["chat_backlog"]["topic"] == CHAT
    assert opening["presence_state"]["topic"] == PRESENCE
    assert opening["chat_backlog"]["payload"]["room"] == ROOM
    assert opening["presence_state"]["payload"]["scope"] == ROOM

    await comm.disconnect()


async def test_posting_reaches_everyone_in_the_room(app: Any) -> None:
    ana, _ = await join(app, "ana")
    bo, _ = await join(app, "bo")
    await receive_json(ana, 1)  # ana sees bo join

    await ana.send_message(
        ChatSendMessage(payload=ChatSendPayload(body="hi all")), topic=CHAT
    )

    (ana_copy,) = await receive_json(ana, 1)
    (bo_copy,) = await receive_json(bo, 1)

    assert ana_copy["action"] == "chat_message"
    assert ana_copy["payload"]["body"] == "hi all"
    assert ana_copy["payload"]["author"]["id"] == "ana"
    assert bo_copy["payload"]["id"] == ana_copy["payload"]["id"]

    await bo.disconnect()
    await ana.disconnect()


async def test_backlog_is_replayed_to_a_later_connection(app: Any) -> None:
    ana, _ = await join(app, "ana")
    await ana.send_message(
        ChatSendMessage(payload=ChatSendPayload(body="first")), topic=CHAT
    )
    await receive_json(ana, 1)

    bo, opening = await join(app, "bo")

    assert [e["body"] for e in opening["chat_backlog"]["payload"]["entries"]] == [
        "first"
    ]

    await bo.disconnect()
    await ana.disconnect()


async def test_backlog_is_capped(app: Any) -> None:
    ana, _ = await join(app, "ana")

    for index in range(5):
        await ana.send_message(
            ChatSendMessage(payload=ChatSendPayload(body=f"m{index}")), topic=CHAT
        )
    await receive_json(ana, 5)

    entries = await ChatTopicForTests.history(ROOM, limit=3)

    assert [e.body for e in entries] == ["m2", "m3", "m4"]
    await ana.disconnect()


async def test_other_rooms_do_not_receive_the_message(app: Any) -> None:
    ana, _ = await join(app, "ana")
    elsewhere, _ = await join(app, "bo", room="other")

    await ana.send_message(
        ChatSendMessage(payload=ChatSendPayload(body="private")), topic=CHAT
    )
    await receive_json(ana, 1)

    await assert_silent(elsewhere)

    await elsewhere.disconnect()
    await ana.disconnect()


async def test_a_bot_can_post_without_a_connection(app: Any) -> None:
    ana, _ = await join(app, "ana")

    await ChatTopicForTests.post_to_room(
        ROOM, "deploy finished", ChatAuthor(id="bot", name="CI")
    )

    (message,) = await receive_json(ana, 1)

    assert message["payload"]["body"] == "deploy finished"
    assert message["payload"]["author"]["name"] == "CI"
    await ana.disconnect()


async def test_leaving_is_announced_to_the_room(app: Any) -> None:
    ana, _ = await join(app, "ana")
    bo, _ = await join(app, "bo")
    await receive_json(ana, 1)  # bo joined

    await bo.disconnect()
    (notice,) = await receive_json(ana, 1)

    assert notice["action"] == "presence_leave"
    assert notice["payload"]["member"]["id"] == "bo"

    await ana.disconnect()


async def test_history_can_be_requested_without_reconnecting(app: Any) -> None:
    ana, _ = await join(app, "ana")
    await ana.send_message(
        ChatSendMessage(payload=ChatSendPayload(body="first")), topic=CHAT
    )
    await receive_json(ana, 1)

    await ana.send_message(
        ChatBacklogRequestMessage(payload=ChatBacklogRequestPayload(limit=5)),
        topic=CHAT,
        ref="9",
    )
    (backlog,) = await receive_json(ana, 1)

    assert backlog["action"] == "chat_backlog"
    assert [e["body"] for e in backlog["payload"]["entries"]] == ["first"]
    assert backlog["ref"] == "9"
    await ana.disconnect()


async def test_chat_works_without_presence(app: Any) -> None:
    """Listing kits means either can be used alone, which stacking prevented."""
    comm = communicator(app, f"{PATH}?as=ana", RoomConsumer)
    await comm.connect()
    await comm.subscribe(CHAT)

    (backlog,) = await receive_json(comm, 1)

    assert backlog["action"] == "chat_backlog"
    assert await PresenceTopicForTests.members_of(ROOM) == []

    await comm.disconnect()
