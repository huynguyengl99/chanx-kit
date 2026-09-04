from datetime import UTC, datetime

from django.test import AsyncClient

import pytest

from ...room_chat.messages import ChatAuthor, ChatEntry
from ...room_chat.store import MessageStore
from ..models import ChatEntryRecord
from ..store import DjangoMessageStore

ROOM = "general"

pytestmark = pytest.mark.django_db(transaction=True)


def entry(body: str, *, room: str = ROOM, minute: int = 0) -> ChatEntry:
    return ChatEntry(
        body=body,
        room=room,
        author=ChatAuthor(id="ana", name="Ana"),
        sent_at=datetime(2026, 1, 1, 12, minute, tzinfo=UTC),
    )


@pytest.fixture
def store() -> DjangoMessageStore:
    return DjangoMessageStore()


def test_satisfies_the_message_store_protocol(store: DjangoMessageStore) -> None:
    assert isinstance(store, MessageStore)


async def test_an_appended_message_comes_back(store: DjangoMessageStore) -> None:
    await store.append(entry("hello"))

    (stored,) = await store.backlog(ROOM, 10)

    assert stored.body == "hello"
    assert stored.author.id == "ana"
    assert stored.author.name == "Ana"


async def test_the_entry_id_survives_a_round_trip(store: DjangoMessageStore) -> None:
    """Clients match websocket messages against fetched history by this id."""
    original = entry("hello")

    await store.append(original)
    (stored,) = await store.backlog(ROOM, 10)

    assert stored.id == original.id


async def test_backlog_is_oldest_first(store: DjangoMessageStore) -> None:
    for minute, body in enumerate(["first", "second", "third"]):
        await store.append(entry(body, minute=minute))

    assert [e.body for e in await store.backlog(ROOM, 10)] == [
        "first",
        "second",
        "third",
    ]


async def test_the_limit_keeps_the_latest_and_still_reads_oldest_first(
    store: DjangoMessageStore,
) -> None:
    """A limit that took the *first* rows would replay the start of a busy room."""
    for minute, body in enumerate(["first", "second", "third"]):
        await store.append(entry(body, minute=minute))

    assert [e.body for e in await store.backlog(ROOM, 2)] == ["second", "third"]


async def test_rooms_do_not_leak_into_each_other(store: DjangoMessageStore) -> None:
    await store.append(entry("here", room=ROOM))
    await store.append(entry("elsewhere", room="random"))

    assert [e.body for e in await store.backlog(ROOM, 10)] == ["here"]


async def test_an_empty_room_has_no_backlog(store: DjangoMessageStore) -> None:
    assert await store.backlog("never-used", 10) == []


async def test_history_is_readable_over_rest(store: DjangoMessageStore) -> None:
    await store.append(entry("hello"))
    await store.append(entry("elsewhere", room="random"))

    response = await AsyncClient().get("/api/chat/history/", {"room": ROOM})

    assert response.status_code == 200
    body = response.json()
    assert [item["body"] for item in body["results"]] == ["hello"]
    assert body["results"][0]["author"] == {"id": "ana", "name": "Ana"}


async def test_rest_reports_the_kit_entry_id_not_the_row_id(
    store: DjangoMessageStore,
) -> None:
    original = entry("hello")
    await store.append(original)

    response = await AsyncClient().get("/api/chat/history/", {"room": ROOM})

    assert response.json()["results"][0]["id"] == original.id


async def test_history_is_read_only(store: DjangoMessageStore) -> None:
    """Writing here would persist a message no connected client is told about."""
    response = await AsyncClient().post(
        "/api/chat/history/", {"room": ROOM, "body": "smuggled"}
    )

    assert response.status_code == 405
    assert await ChatEntryRecord.objects.acount() == 0
