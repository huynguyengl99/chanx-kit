"""AG-UI over chanx websockets."""

import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

from chanx.core.decorators import ws_handler
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage

from ag_ui.core import (
    Event,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
)

from .messages import AgUiEventMessage, AgUiRunMessage


class AgUiBaseTopic(Topic[AgUiEventMessage]):
    """Serialisation shared by every AG-UI topic."""

    passthrough_events: ClassVar[list[type[BaseMessage]]] = [AgUiEventMessage]

    # AG-UI is camelCase on the wire. Aliases rename only declared fields, so opaque
    # ``state`` / ``forwardedProps`` survive verbatim, unlike a blanket camelizer.
    send_by_alias: ClassVar[bool] = True

    async def send_message(
        self, message: BaseMessage, *, validate: bool = False
    ) -> None:
        # A dump-time flag rather than model config: serialize_by_alias is not
        # inherited by nested third-party AG-UI models.
        if not self.send_by_alias:
            await super().send_message(message, validate=validate)
            return
        await self.send_json(message.model_dump(mode="json", by_alias=True))


class AgUiTopic(AgUiBaseTopic):
    """Serve the [AG-UI protocol](https://ag-ui.com) over a chanx websocket,
    addressed per thread: ``agui:thread:<thread_id>``. Provider-agnostic: override
    :meth:`run_agent` to yield AG-UI events."""

    pattern = "agui:thread:{thread_id}"

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        """Yield AG-UI content events for one run; ``RUN_STARTED`` / ``RUN_FINISHED``
        are emitted around whatever you yield."""
        raise NotImplementedError(
            f"{type(self).__name__} must override run_agent() to produce AG-UI events. "
            "See the kit's README for a pydantic-ai example."
        )
        yield  # pragma: no cover - marks this as an async generator

    @ws_handler(
        summary="Run the agent",
        description="Run an AG-UI agent and stream its events back.",
        output_type=AgUiEventMessage,
    )
    async def handle_ag_ui_run(self, message: AgUiRunMessage) -> None:
        run_input = message.payload
        run_id = run_input.run_id or self.new_run_id()
        # run_agent and anything it hands the run to must see the id the client is
        # about to be told about, not the empty one it sent.
        run_input.run_id = run_id

        await self.emit(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=run_input.thread_id,
                run_id=run_id,
            )
        )

        try:
            async for event in self.run_agent(run_input):
                await self.emit(event)
        except Exception as error:  # noqa: BLE001 - surfaced to the client as RUN_ERROR
            await self.on_run_error(run_input, error)
            return

        await self.emit(
            RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=run_input.thread_id,
                run_id=run_id,
            )
        )

    async def on_run_error(self, run_input: RunAgentInput, error: Exception) -> None:
        """Report a failed run as ``RUN_ERROR``. Override to log or redact."""
        await self.emit(RunErrorEvent(type=EventType.RUN_ERROR, message=str(error)))

    async def emit(self, event: Event) -> None:
        """Send straight down this socket, never through the run group: a group hop
        could reorder AG-UI events."""
        await self.send_message(AgUiEventMessage(payload=event))

    @classmethod
    async def emit_to_thread(cls, thread_id: str, event: Event) -> None:
        """Emit into a conversation from outside the connection, reaching every client
        already subscribed to it. Prefer this over :class:`AgUiRunTopic` unless the
        caller must target one run: no client has to know a run id in advance."""
        await cls.broadcast(f"agui:thread:{thread_id}", AgUiEventMessage(payload=event))


class AgUiRunTopic(AgUiBaseTopic):
    """One run's events: ``agui:run:<run_id>``. Lets work happening off the connection
    (a worker, a graph node, a tool) emit by run id, and a client subscribes to the run
    it started."""

    pattern = "agui:run:{run_id}"

    @classmethod
    async def emit_to_run(cls, run_id: str, event: Event) -> None:
        """Emit an event into a run from outside the connection."""
        await cls.broadcast(f"agui:run:{run_id}", AgUiEventMessage(payload=event))
