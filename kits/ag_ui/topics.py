"""AG-UI over chanx websockets."""

import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

from chanx.core.decorators import ws_handler
from chanx.core.envelope import current_seq
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
from .store import InMemoryRunEventStore, RunEventStore

RUN_TERMINAL_EVENTS = frozenset({EventType.RUN_FINISHED, EventType.RUN_ERROR})


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

    broadcast_run_events: ClassVar[bool] = False

    run_event_store: ClassVar[RunEventStore] = InMemoryRunEventStore()

    @property
    def thread_id(self) -> str:
        return self.params["thread_id"]

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    async def on_subscribe(self) -> None:
        """Replay the run in flight: AG-UI cannot join a stream part-way through."""
        if not self.broadcast_run_events:
            return
        for seq, event in await self.run_event_store.replay(self.thread_id):
            await self.send_run_event(event, seq=seq)

    async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        """Yield this run's content events; the lifecycle is added around them."""
        raise NotImplementedError(
            f"{type(self).__name__} must override run_agent() to produce AG-UI events, "
            "or run_events() if its provider emits the run lifecycle itself."
        )
        yield  # pragma: no cover - marks this as an async generator

    async def run_events(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        """One run's whole stream. Override instead of :meth:`run_agent` when the
        provider emits its own lifecycle, whose outcome must not be replaced."""
        yield RunStartedEvent(
            type=EventType.RUN_STARTED,
            thread_id=run_input.thread_id,
            run_id=run_input.run_id,
        )
        async for event in self.run_agent(run_input):
            yield event
        yield RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            thread_id=run_input.thread_id,
            run_id=run_input.run_id,
        )

    @ws_handler(
        summary="Run the agent",
        description="Run an AG-UI agent and stream its events back.",
        output_type=AgUiEventMessage,
    )
    async def handle_ag_ui_run(self, message: AgUiRunMessage) -> None:
        run_input = message.payload
        run_input.run_id = run_input.run_id or self.new_run_id()

        try:
            async for event in self.run_events(run_input):
                await self.emit(event)
        except Exception as error:  # noqa: BLE001 - surfaced to the client as RUN_ERROR
            await self.on_run_error(run_input, error)

    async def on_run_error(self, run_input: RunAgentInput, error: Exception) -> None:
        """Report a failed run as ``RUN_ERROR``. Override to log or redact."""
        await self.emit(RunErrorEvent(type=EventType.RUN_ERROR, message=str(error)))

    async def emit(self, event: Event) -> None:
        """Send one of this run's events, to this socket or to the whole thread."""
        if not self.broadcast_run_events:
            await self.send_run_event(event, seq=None)
            return
        await self.broadcast_run_event(self.thread_id, event)

    async def send_run_event(self, event: Event, *, seq: int | None) -> None:
        token = current_seq.set(seq)
        try:
            await self.send_message(AgUiEventMessage(payload=event))
        finally:
            current_seq.reset(token)

    @classmethod
    async def broadcast_run_event(cls, thread_id: str, event: Event) -> None:
        if event.type == EventType.RUN_STARTED:
            await cls.run_event_store.clear(thread_id)

        seq = await cls.run_event_store.append(thread_id, event)
        await cls.broadcast(
            f"agui:thread:{thread_id}", AgUiEventMessage(payload=event), seq=seq
        )

        if event.type in RUN_TERMINAL_EVENTS:
            await cls.run_event_store.clear(thread_id)

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
