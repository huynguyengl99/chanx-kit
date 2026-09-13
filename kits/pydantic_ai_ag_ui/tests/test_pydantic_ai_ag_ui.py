from collections.abc import AsyncIterator, Iterator
from typing import Any, ClassVar

import pytest
from chanx.core.topic import Topic
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

from ag_ui.core import RunAgentInput, UserMessage

from ...ag_ui.messages import AgUiRunMessage
from ...chanx_testing import (
    KitConsumer,
    assert_silent,
    build_app,
    communicator,
    receive_json,
    setup_memory_layer,
)
from ...conversation_store.store import InMemoryConversationStore
from ..topics import PydanticAIAgUiTopic

PATH = "/ws/agent"
THREAD = "agui:thread:thread-1"

CONVERSATION_STORE = InMemoryConversationStore()

# Message count per run, proving the agent saw history the client never sent.
PROMPTS_SEEN: list[int] = []


async def stream_function(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    """First turn calls the approval-gated tool; once approved, it answers."""
    PROMPTS_SEEN.append(len(messages))
    if not any(isinstance(message, ModelResponse) for message in messages):
        yield {
            0: DeltaToolCall(
                name="delete_task", json_args='{"task": "7"}', tool_call_id="call-1"
            )
        }
    else:
        yield "Task 7 "
        yield "is gone."


agent = Agent(
    FunctionModel(stream_function=stream_function),
    output_type=[str, DeferredToolRequests],
)


@agent.tool_plain(requires_approval=True)
def delete_task(task: str) -> str:
    return f"deleted {task}"


class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent
    conversation_store = CONVERSATION_STORE


class AgentConsumer(KitConsumer):
    channel_layer_alias = "default"
    topics: ClassVar[list[type[Topic[Any]]]] = [TaskletTopic]


@pytest.fixture(autouse=True)
def _layer() -> Iterator[None]:
    setup_memory_layer("default")
    CONVERSATION_STORE.reset()
    PROMPTS_SEEN.clear()
    yield


@pytest.fixture
def app() -> Any:
    return build_app({PATH: AgentConsumer})


def run_input(**overrides: Any) -> RunAgentInput:
    defaults: dict[str, Any] = {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "state": {},
        # Only the new turn: the rest of the conversation is the server's.
        "messages": [UserMessage(id="m1", role="user", content="delete task 7")],
        "tools": [],
        "context": [],
        "forwarded_props": {},
    }
    defaults.update(overrides)
    return RunAgentInput(**defaults)


def types_of(messages: list[dict[str, Any]]) -> list[str]:
    return [m["payload"]["type"] for m in messages]


async def test_a_run_is_bracketed_once(app: Any) -> None:
    """The adapter emits its own lifecycle, so the kit must not add a second one."""
    async with communicator(app, PATH, AgentConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        messages = await receive_json(comm, 5)

    types = types_of(messages)

    assert types.count("RUN_STARTED") == 1
    assert types.count("RUN_FINISHED") == 1
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"


async def test_an_approval_pauses_the_run_and_names_the_interrupt(app: Any) -> None:
    """A `requires_approval` tool reaches the client as an AG-UI interrupt."""
    async with communicator(app, PATH, AgentConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        messages = await receive_json(comm, 5)

    finished = messages[-1]
    outcome = finished["payload"]["outcome"]

    assert types_of(messages) == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "RUN_FINISHED",
    ]
    assert outcome["type"] == "interrupt"
    assert [i["toolCallId"] for i in outcome["interrupts"]] == ["call-1"]


async def test_approving_resumes_the_run_from_server_held_history(app: Any) -> None:
    """Resumed with an interrupt id and no messages: the history never left us."""
    async with communicator(app, PATH, AgentConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)
        paused = await receive_json(comm, 5)
        interrupt_id = paused[-1]["payload"]["outcome"]["interrupts"][0]["id"]

        await comm.send_message(
            AgUiRunMessage(
                payload=run_input(
                    run_id="run-2",
                    messages=[],
                    resume=[
                        {
                            "interruptId": interrupt_id,
                            "status": "resolved",
                            "payload": {"approved": True},
                        }
                    ],
                )
            ),
            topic=THREAD,
        )
        resumed = await receive_json(comm, 7)

    assert types_of(resumed) == [
        "RUN_STARTED",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert resumed[-1]["payload"]["outcome"]["type"] == "success"
    # The resumed run was handed the paused conversation, not an empty one.
    assert PROMPTS_SEEN[-1] > PROMPTS_SEEN[0]


async def test_denying_the_tool_still_resumes_the_run(app: Any) -> None:
    async with communicator(app, PATH, AgentConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)
        paused = await receive_json(comm, 5)
        interrupt_id = paused[-1]["payload"]["outcome"]["interrupts"][0]["id"]

        await comm.send_message(
            AgUiRunMessage(
                payload=run_input(
                    run_id="run-3",
                    resume=[
                        {
                            "interruptId": interrupt_id,
                            "status": "resolved",
                            "payload": {"approved": False, "reason": "Not that one"},
                        }
                    ],
                )
            ),
            topic=THREAD,
        )
        resumed = await receive_json(comm, 8)

    assert types_of(resumed)[:2] == ["RUN_STARTED", "TOOL_CALL_RESULT"]
    assert types_of(resumed)[-1] == "RUN_FINISHED"
    # Denial is a normal outcome: the model is told, and the run carries on.
    assert "Not that one" in str(resumed[1]["payload"]["content"])


async def test_a_topic_without_an_agent_says_so(app: Any) -> None:
    class BareTopic(PydanticAIAgUiTopic):
        pass

    class BareConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [BareTopic]

    async with communicator(
        build_app({PATH: BareConsumer}), PATH, BareConsumer
    ) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)

        error = (await receive_json(comm, 1))[0]

    assert error["payload"]["type"] == "RUN_ERROR"
    assert "must set `agent`" in error["payload"]["message"]


async def test_a_reconnect_is_told_the_conversation(app: Any) -> None:
    """The paper trail: the adapter dumps stored messages into the same format it
    writes live, so a reload needs no replay protocol of its own."""
    async with communicator(app, PATH, AgentConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)
        await receive_json(comm, 5)

    async with communicator(app, PATH, AgentConsumer) as fresh:
        await fresh.subscribe(THREAD)
        first = (await receive_json(fresh, 1))[0]

    assert first["payload"]["type"] == "MESSAGES_SNAPSHOT"
    roles = [m["role"] for m in first["payload"]["messages"]]
    assert roles[0] == "user"
    assert "assistant" in roles


async def test_a_thread_with_no_conversation_sends_no_transcript(app: Any) -> None:
    async with communicator(app, PATH, AgentConsumer) as comm:
        await comm.subscribe("agui:thread:never-used")
        await assert_silent(comm)


async def test_the_transcript_can_be_turned_off(app: Any) -> None:
    """A client that keeps its own messages does not want ours."""

    class QuietTopic(TaskletTopic):
        send_transcript = False

    class QuietConsumer(KitConsumer):
        channel_layer_alias = "default"
        topics: ClassVar[list[type[Topic[Any]]]] = [QuietTopic]

    quiet_app = build_app({PATH: QuietConsumer})

    async with communicator(quiet_app, PATH, QuietConsumer) as comm:
        await comm.subscribe(THREAD)
        await comm.send_message(AgUiRunMessage(payload=run_input()), topic=THREAD)
        await receive_json(comm, 5)

    async with communicator(quiet_app, PATH, QuietConsumer) as fresh:
        await fresh.subscribe(THREAD)
        await assert_silent(fresh)
