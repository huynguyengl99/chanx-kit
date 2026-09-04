from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
from chanx.core.topic import Topic

from ag_ui.core import (
    Event,
    EventType,
    RunAgentInput,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

from ...chanx_testing import (
    KitConsumer,
    assert_silent,
    build_app,
    communicator,
    receive_json,
    receive_until,
    setup_memory_layer,
)
from ..messages import AgUiRunMessage
from ..topics import AgUiRunTopic, AgUiTopic

PATH = "/ws/agent"
THREAD = "agui:thread:thread-1"


def run_input(**overrides: Any) -> RunAgentInput:
    defaults: dict[str, Any] = {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "state": {},
        "messages": [],
        "tools": [],
        "context": [],
        "forwarded_props": {},
    }
    defaults.update(overrides)
    return RunAgentInput(**defaults)


class ScriptedAgUiTopic(AgUiTopic):
    """Yields a fixed text message, the way a provider adapter would."""

    async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        yield TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START, message_id="msg-1"
        )
        yield TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT, message_id="msg-1", delta="Hello"
        )
        yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id="msg-1")


class AgUiConsumer(KitConsumer):
    channel_layer_alias = "default"
    topics: ClassVar[list[type[Topic[Any]]]] = [ScriptedAgUiTopic, AgUiRunTopic]


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")


@pytest.fixture
def app() -> Any:
    return build_app({PATH: AgUiConsumer})


async def test_a_run_is_bracketed_by_started_and_finished(app: Any) -> None:
    async with communicator(app, PATH, AgUiConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        messages = await receive_json(comm, 5)

    types = [m["payload"]["type"] for m in messages]

    assert types == [
        "RUN_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert {m["action"] for m in messages} == {"ag_ui_event"}


async def test_events_are_camel_case_on_the_wire(app: Any) -> None:
    """AG-UI clients read camelCase; snake_case would be silently incompatible."""
    async with communicator(app, PATH, AgUiConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        started = await receive_until(comm, "ag_ui_event")
        content = (await receive_json(comm, 2))[1]

    assert "threadId" in started["payload"]
    assert "thread_id" not in started["payload"]
    assert content["payload"]["messageId"] == "msg-1"
    assert "message_id" not in content["payload"]


async def test_opaque_state_keys_are_never_rewritten(app: Any) -> None:
    """`state` is the user's own JSON. A blanket camelizer would corrupt it."""

    class EchoStateTopic(ScriptedAgUiTopic):
        async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
            from ag_ui.core import StateSnapshotEvent

            yield StateSnapshotEvent(
                type=EventType.STATE_SNAPSHOT, snapshot=run_input.state
            )

    class EchoConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [EchoStateTopic, AgUiRunTopic]

    echo_app = build_app({PATH: EchoConsumer})
    state = {"user_profile": {"first_name": "Ana"}, "API_KEY_ref": 1}

    async with communicator(echo_app, PATH, EchoConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(
            AgUiRunMessage(payload=run_input(state=state)), topic=THREAD
        )

        await receive_json(comm, 1)  # RUN_STARTED
        snapshot = (await receive_json(comm, 1))[0]

    assert snapshot["payload"]["snapshot"] == state


async def test_camel_case_input_from_the_wire_is_accepted(app: Any) -> None:
    """An AG-UI client sends camelCase; it has to parse without translation."""
    async with communicator(app, PATH, AgUiConsumer) as comm:
        await comm.subscribe("agui:thread:thread-9")
        await comm.send_json_to(
            {
                "version": 1,
                "topic": "agui:thread:thread-9",
                "action": "ag_ui_run",
                "payload": {
                    "threadId": "thread-9",
                    "runId": "run-9",
                    "state": {},
                    "messages": [],
                    "tools": [],
                    "context": [],
                    "forwardedProps": {},
                },
            }
        )

        started = (await receive_json(comm, 1))[0]

    assert started["payload"]["type"] == "RUN_STARTED"
    assert started["payload"]["threadId"] == "thread-9"
    assert started["payload"]["runId"] == "run-9"


async def test_a_failing_provider_becomes_run_error(app: Any) -> None:
    class FailingTopic(AgUiTopic):
        async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
            raise RuntimeError("provider exploded")
            yield  # pragma: no cover

    class FailingConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [FailingTopic, AgUiRunTopic]

    failing_app = build_app({PATH: FailingConsumer})

    async with communicator(failing_app, PATH, FailingConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        await receive_json(comm, 1)  # RUN_STARTED
        error = (await receive_json(comm, 1))[0]

    assert error["payload"]["type"] == "RUN_ERROR"
    assert "provider exploded" in error["payload"]["message"]


async def test_a_kit_without_run_agent_says_what_to_override(app: Any) -> None:
    class BareTopic(AgUiTopic):
        pass

    class BareConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [BareTopic, AgUiRunTopic]

    bare_app = build_app({PATH: BareConsumer})

    async with communicator(bare_app, PATH, BareConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        await receive_json(comm, 1)  # RUN_STARTED
        error = (await receive_json(comm, 1))[0]

    assert "must override run_agent()" in error["payload"]["message"]


async def test_a_generated_run_id_reaches_run_agent(app: Any) -> None:
    """A worker keyed off ``run_input.run_id`` would emit to an empty address if the
    generated id were only put on RUN_STARTED."""
    seen: list[str] = []

    class RecordingTopic(ScriptedAgUiTopic):
        def new_run_id(self) -> str:
            return "generated-1"

        async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
            seen.append(run_input.run_id)
            async for event in super().run_agent(run_input):
                yield event

    class RecordingConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [RecordingTopic, AgUiRunTopic]

    async with communicator(
        build_app({PATH: RecordingConsumer}), PATH, RecordingConsumer
    ) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(
            AgUiRunMessage(payload=run_input(run_id="")), topic=THREAD
        )
        started = (await receive_json(comm, 5))[0]

    assert seen == ["generated-1"]
    assert started["payload"]["runId"] == "generated-1"


def test_a_run_gets_its_own_group() -> None:
    assert AgUiRunTopic.group_name("agui:run:run-1") != AgUiRunTopic.group_name(
        "agui:run:run-2"
    )


async def test_own_run_events_stay_in_order(app: Any) -> None:
    """Own events are sent directly, never through the run group, so a content delta
    cannot overtake its ``TEXT_MESSAGE_START``."""
    async with communicator(app, PATH, AgUiConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        types = [m["payload"]["type"] for m in await receive_json(comm, 5)]

    assert types == [
        "RUN_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]


async def test_another_process_can_emit_into_a_thread(app: Any) -> None:
    """The thread subscription the client already has is enough: no run id up front."""
    async with communicator(app, PATH, AgUiConsumer) as comm:
        await comm.subscribe(THREAD)

        await ScriptedAgUiTopic.emit_to_thread(
            "thread-1",
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id="msg-3",
                delta="from a worker",
            ),
        )
        event = (await receive_json(comm, 1))[0]

    assert event["payload"]["delta"] == "from a worker"
    assert event["payload"]["messageId"] == "msg-3"


async def test_a_thread_emit_does_not_reach_another_thread(app: Any) -> None:
    async with communicator(app, PATH, AgUiConsumer) as comm:
        await comm.subscribe(THREAD)

        await ScriptedAgUiTopic.emit_to_thread(
            "thread-2",
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT, message_id="msg-4", delta="nope"
            ),
        )

        await assert_silent(comm)


async def test_another_process_can_emit_into_a_run(app: Any) -> None:
    """What ``sandbox/worker.py`` demonstrates: no consumer, no socket, just a run id."""
    async with communicator(app, PATH, AgUiConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.subscribe("agui:run:run-1", ref="2")
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)
        await receive_json(comm, 5)

        await AgUiRunTopic.emit_to_run(
            "run-1",
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id="msg-2",
                delta="from a worker",
            ),
        )
        event = (await receive_json(comm, 1))[0]

    assert event["payload"]["delta"] == "from a worker"
    assert event["payload"]["messageId"] == "msg-2"
