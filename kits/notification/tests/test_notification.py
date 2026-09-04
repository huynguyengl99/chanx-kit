from typing import Any, ClassVar

import pytest
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage

from ...chanx_testing import (
    KitConsumer,
    assert_silent,
    build_app,
    communicator,
    receive_json,
    setup_memory_layer,
)
from ..messages import (
    NotificationAckMessage,
    NotificationAckPayload,
    NotificationLevel,
    NotificationMessage,
    NotificationPayload,
)
from ..topics import (
    BroadcastNotificationTopic,
    SubjectNotificationTopic,
    UserNotificationTopic,
)

PATH = "/ws/notifications"


class RecordingUserTopic(UserNotificationTopic):
    acked: ClassVar[list[str]] = []

    def current_user_id(self) -> str | None:
        return "42"

    async def on_notifications_acked(self, ids: list[str]) -> None:
        type(self).acked.extend(ids)


class NotificationConsumer(KitConsumer):
    channel_layer_alias = "default"
    topics: ClassVar[list[type[Topic[Any]]]] = [
        RecordingUserTopic,
        SubjectNotificationTopic,
        BroadcastNotificationTopic,
    ]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")
    RecordingUserTopic.acked.clear()


@pytest.fixture
def app() -> Any:
    return build_app({PATH: NotificationConsumer})


async def test_notification_reaches_the_addressed_user(app: Any) -> None:
    async with communicator(app, PATH, NotificationConsumer) as comm:
        await comm.subscribe("notification:user:42")

        await RecordingUserTopic.notify_user(
            "42", NotificationPayload(title="Build finished", body="all green")
        )

        (message,) = await receive_json(comm, 1)

    assert message["action"] == "notification"
    assert message["payload"]["title"] == "Build finished"
    assert message["payload"]["level"] == NotificationLevel.INFO
    assert message["topic"] == "notification:user:42"


async def test_another_users_notifications_cannot_even_be_subscribed(app: Any) -> None:
    """Previously the audience was server-derived, so this could not be expressed."""
    async with communicator(app, PATH, NotificationConsumer) as comm:
        denied = await comm.subscribe("notification:user:99")

        assert denied["action"] == "error"
        assert denied["payload"]["reason"] == "unauthorized"

        await RecordingUserTopic.notify_user("99", NotificationPayload(title="No"))
        await assert_silent(comm)


async def test_broadcast_and_subject_reach_the_connection(app: Any) -> None:
    async with communicator(app, PATH, NotificationConsumer) as comm:
        await comm.subscribe("notification:all")
        await comm.subscribe("notification:subject:billing", ref="2")

        await BroadcastNotificationTopic.notify_all(NotificationPayload(title="All"))
        await SubjectNotificationTopic.notify_subject(
            "billing", NotificationPayload(title="Subject")
        )

        messages = await receive_json(comm, 2)

    assert sorted(m["payload"]["title"] for m in messages) == ["All", "Subject"]


async def test_ack_is_confirmed_and_recorded(app: Any) -> None:
    async with communicator(app, PATH, NotificationConsumer) as comm:
        await comm.subscribe("notification:user:42")

        await comm.send_message(
            NotificationAckMessage(payload=NotificationAckPayload(ids=["a", "b"])),
            topic="notification:user:42",
        )

        (reply,) = await receive_json(comm, 1)

    assert reply["action"] == "notification_acked"
    assert reply["payload"]["ids"] == ["a", "b"]
    assert RecordingUserTopic.acked == ["a", "b"]


async def test_unsubscribing_stops_delivery(app: Any) -> None:
    async with communicator(app, PATH, NotificationConsumer) as comm:
        await comm.subscribe("notification:all")
        await comm.unsubscribe("notification:all", ref="2")

        await BroadcastNotificationTopic.notify_all(NotificationPayload(title="Gone"))
        await assert_silent(comm)


def test_notification_message_is_a_passthrough_event() -> None:
    passthrough: list[type[BaseMessage]] = UserNotificationTopic.passthrough_events
    assert NotificationMessage in passthrough


def test_topics_get_distinct_groups() -> None:
    """Each audience is its own group, so they cannot collide."""
    names = {
        UserNotificationTopic.group_name("notification:user:42"),
        SubjectNotificationTopic.group_name("notification:subject:billing"),
        BroadcastNotificationTopic.group_name("notification:all"),
    }

    assert len(names) == 3
    assert all(len(name) < 100 for name in names)
