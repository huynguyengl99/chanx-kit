"""Drive an agent run from a background worker.

    # terminal 1
    REDIS_URL=redis://localhost:6399/0 uv run python -m sandbox
    # terminal 2: connect a client to /ws/agent, subscribe to agui:run:<run-id>, then:
    REDIS_URL=redis://localhost:6399/0 uv run python -m sandbox.worker <run-id>

The shape a task queue or a tool runner would take: the work does not own the
WebSocket, and whichever process does forwards what this publishes.

It addresses a run because that is what the command line hands it. Reaching the whole
conversation with ``AgUiTopic.emit_to_thread`` is usually simpler, since the client is
already subscribed and needs no run id up front.
"""

import asyncio
import os
import sys
from uuid import uuid4

from kits.ag_ui import AgUiRunTopic

from ag_ui.core import (
    EventType,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from sandbox.layers import setup_layers

STEPS = [
    "Looking that up",
    " in the background,",
    " on a worker that never saw the socket.",
]


async def run_a_tool(run_id: str) -> None:
    tool_call_id = uuid4().hex
    await AgUiRunTopic.emit_to_run(
        run_id,
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tool_call_id,
            tool_call_name="search_docs",
        ),
    )
    await AgUiRunTopic.emit_to_run(
        run_id,
        ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS,
            tool_call_id=tool_call_id,
            delta='{"query": "ag-ui over websockets"}',
        ),
    )
    await asyncio.sleep(0.4)
    await AgUiRunTopic.emit_to_run(
        run_id,
        ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id),
    )


async def stream_an_answer(run_id: str) -> None:
    message_id = uuid4().hex
    await AgUiRunTopic.emit_to_run(
        run_id,
        TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id),
    )
    for chunk in STEPS:
        await AgUiRunTopic.emit_to_run(
            run_id,
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=chunk,
            ),
        )
        await asyncio.sleep(0.3)
    await AgUiRunTopic.emit_to_run(
        run_id,
        TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id),
    )


async def main() -> None:
    if not os.environ.get("REDIS_URL"):
        raise SystemExit(
            "REDIS_URL is not set. The sandbox falls back to an in-memory channel "
            "layer, which cannot cross process boundaries, so this worker would emit "
            "into its own layer and nothing would reach the browser.\n"
            "Start the server and this worker with the same REDIS_URL."
        )

    arguments = sys.argv[1:]
    if not arguments:
        raise SystemExit(
            "Usage: python -m sandbox.worker <run-id>\n"
            "The run id is the one the client sent in its ag_ui_run message."
        )

    setup_layers()
    run_id = arguments[0]

    print(f"Emitting into run {run_id} ...")
    await run_a_tool(run_id)
    await stream_an_answer(run_id)
    print("Done. The client saw these events as part of the same run.")


if __name__ == "__main__":
    asyncio.run(main())
