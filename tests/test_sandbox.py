"""Smoke tests for the sandbox app — the reference for composing kits and the source
the TypeScript generator reads, so kit messages must reach the AsyncAPI document."""

import os
import pathlib
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CHANX_KIT_BACKEND") == "channels",
    reason="the sandbox is the FastAPI reference app",
)


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from sandbox.main import app

    response = TestClient(app).get("/asyncapi.json")
    assert response.status_code == 200
    return response.json()


def test_every_route_and_its_topics_are_published(spec: dict[str, Any]) -> None:
    """A topic is documented as its own channel, sharing its route's address."""
    channels = spec["channels"]

    assert {"notifications", "room", "agent"} <= set(channels)
    assert {"room_demo_chat_topic", "room_demo_presence_topic"} <= set(channels)

    # topics share the address of the route hosting them
    room_address = channels["room"]["address"]
    for name in ("room_demo_chat_topic", "room_demo_presence_topic"):
        assert channels[name]["address"] == room_address
        assert channels[name]["x-topic"]["pattern"]


def test_each_kit_keeps_its_own_messages(spec: dict[str, Any]) -> None:
    """Scoping is the point: chat messages belong to chat, presence to presence."""
    chat = set(spec["channels"]["room_demo_chat_topic"]["messages"])
    presence = set(spec["channels"]["room_demo_presence_topic"]["messages"])

    assert {"chat_message", "chat_send_message"} <= chat
    assert {"presence_join_message", "presence_leave_message"} <= presence
    assert "presence_join_message" not in chat


def test_messages_pushed_on_subscribe_are_declared(spec: dict[str, Any]) -> None:
    # Sent from on_subscribe, not returned by a handler; chanx only discovers
    # messages through handlers, so each kit exposes an explicit request message.
    chat = set(spec["channels"]["room_demo_chat_topic"]["messages"])
    presence = set(spec["channels"]["room_demo_presence_topic"]["messages"])

    assert "chat_backlog_message" in chat
    assert "presence_state_message" in presence


def test_agent_channel_speaks_ag_ui(spec: dict[str, Any]) -> None:
    """The whole protocol travels in two messages, keyed on payload.type."""
    agent = set(spec["channels"]["agent_demo_ag_ui_topic"]["messages"])

    assert {"ag_ui_run_message", "ag_ui_event_message"} <= agent


def test_kits_are_listed_rather_than_stacked() -> None:
    """Each kit keeps its own handlers, so neither has to know about the other."""
    from sandbox.consumers import RoomConsumer

    mounted = {
        topic.__name__: set(topic._MESSAGE_HANDLER_INFO_MAP)
        for topic in RoomConsumer.topics
    }

    assert {"chat_send", "chat_backlog_request"} <= mounted["DemoChatTopic"]
    assert "presence_request" in mounted["DemoPresenceTopic"]
    # the consumer keeps its own un-addressed handlers
    assert "ping" in RoomConsumer._MESSAGE_HANDLER_INFO_MAP


def test_every_kit_topic_gets_its_own_group() -> None:
    """Topics reach the channel layer themselves, with no binding step."""
    from sandbox.consumers import AgentConsumer, NotificationConsumer, RoomConsumer

    groups = {
        topic.group_name(topic.pattern.format(**dict.fromkeys(topic.param_names, "x")))
        for consumer in (NotificationConsumer, RoomConsumer, AgentConsumer)
        for topic in consumer.topics
    }

    assert len(groups) == sum(
        len(c.topics) for c in (NotificationConsumer, RoomConsumer, AgentConsumer)
    )


def test_every_kit_message_is_reachable_from_the_sandbox(spec: dict[str, Any]) -> None:
    """The sandbox is what freezes the wire contract, so it has to cover every kit.

    CI regenerates the TypeScript types from this schema and fails on any diff. That
    only protects messages the sandbox actually exposes — a kit nobody mounts here
    would have no contract check at all.
    """
    import importlib
    import inspect
    import json

    from chanx.messages.base import BaseMessage

    documented = set(spec["components"]["schemas"])
    registry = json.loads(
        (
            pathlib.Path(__file__).resolve().parent.parent / "copit-registry.json"
        ).read_text()
    )

    uncovered: dict[str, list[str]] = {}
    for name, component in registry["components"].items():
        package = pathlib.Path(component["path"]).name
        # Scan the messages module, not the package: unexported messages are exactly
        # the gap this test is for.
        try:
            module = importlib.import_module(f"kits.{package}.messages")
        except ModuleNotFoundError:
            continue

        messages = {
            obj.__name__
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BaseMessage)
            and obj is not BaseMessage
            and obj.__module__ == module.__name__
        }
        missing = sorted(messages - documented)
        if missing:
            uncovered[name] = missing

    assert not uncovered, (
        f"These kit messages are not exposed by any sandbox consumer, so no CI check "
        f"freezes their wire contract: {uncovered}. Mount the kit in sandbox/consumers.py."
    )
