"""AG-UI over chanx websockets."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any, ClassVar

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

from .messages import AgUiCancelMessage, AgUiEventMessage, AgUiRunMessage
from .store import (
    ActiveRunStore,
    InMemoryActiveRunStore,
    InMemoryRunEventStore,
    RunEventStore,
)

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

    # A provider that keeps the conversation tells a reconnecting client about it
    # rather than leaving a blank page. Turn off when the client keeps its own.
    send_transcript: ClassVar[bool] = True

    run_event_store: ClassVar[RunEventStore] = InMemoryRunEventStore()

    active_run_store: ClassVar[ActiveRunStore] = InMemoryActiveRunStore()

    # A task handle cannot leave the process holding it, so unlike the stores above
    # this is a plain registry rather than a protocol: a cancel stops a run only on
    # the process that is running it.
    _run_tasks: ClassVar[dict[tuple[str, str], "asyncio.Task[None]"]] = {}

    def __init__(self, consumer: Any, topic: str) -> None:
        super().__init__(consumer, topic)
        # The runs this connection started, so leaving can take them with it.
        self._own_runs: set[tuple[str, str]] = set()

    @property
    def thread_id(self) -> str:
        return self.params["thread_id"]

    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    async def transcript(self) -> Event | None:
        """The conversation a reconnecting client should be shown, if any.

        Nothing by default: only a provider that keeps the conversation knows how
        to render it, usually as ``MESSAGES_SNAPSHOT``.
        """
        return None

    async def send_initial_state(self) -> None:
        """What a new connection is told before the run in flight is replayed.

        Override to add your own state, calling ``super()`` first: whatever goes
        here must land before the replay, or replayed events race it.
        """
        if not self.send_transcript:
            return
        transcript = await self.transcript()
        if transcript is not None:
            await self.send_run_event(transcript, seq=None)

    async def on_subscribe(self) -> None:
        """State first, then the run in flight: AG-UI cannot join a stream
        part-way through, so the run is replayed rather than picked up."""
        await self.send_initial_state()
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

        # A thread runs one run at a time. Two overlapping runs would share the
        # thread's event buffer and its sequence, so the second would reset the
        # sequence mid-conversation and leave a joining connection replaying a
        # stream that starts part-way through a message.
        active_run_id = await self.active_run_store.begin(
            self.thread_id, run_input.run_id
        )
        if active_run_id is not None:
            await self.on_run_refused(run_input, active_run_id)
            return

        # The stream runs as its own task so a cancel has something to stop. Cancelling
        # the handler instead would leave nothing running to report the outcome.
        key = (self.thread_id, run_input.run_id)
        run_task: asyncio.Task[None] = asyncio.ensure_future(
            self._stream_run(run_input)
        )
        self._run_tasks[key] = run_task
        self._own_runs.add(key)
        try:
            await run_task
        except asyncio.CancelledError:
            if not run_task.cancelled():
                raise  # this handler is being torn down, not the run
            await self.on_run_cancelled(run_input)
        except Exception as error:  # noqa: BLE001 - surfaced to the client as RUN_ERROR
            await self.on_run_error(run_input, error)
        finally:
            if not run_task.done():
                run_task.cancel()
            self._run_tasks.pop(key, None)
            self._own_runs.discard(key)
            await self.active_run_store.end(self.thread_id, run_input.run_id)

    async def on_unsubscribe(self) -> None:
        """Take this connection's runs with it when it leaves.

        Only when the run is not broadcast. Then its events go to this socket alone,
        so once the socket is gone no one can ever see the rest of it and producing
        it is pure cost. A broadcast run belongs to the thread instead, and the other
        tabs watching it are the reason it keeps going.
        """
        await super().on_unsubscribe()
        if self.broadcast_run_events:
            return
        for key in list(self._own_runs):
            run_task = self._run_tasks.get(key)
            if run_task is not None and not run_task.done():
                run_task.cancel()

    async def _stream_run(self, run_input: RunAgentInput) -> None:
        async for event in self.run_events(run_input):
            await self.emit(event)

    @ws_handler(
        summary="Cancel the run",
        description="Stop the run in flight on this thread.",
        output_type=AgUiEventMessage,
    )
    async def handle_ag_ui_cancel(self, message: AgUiCancelMessage) -> None:
        run_task = self._run_tasks.get((self.thread_id, message.payload.run_id))
        # Nothing to stop: the run ended on its own, and its terminal event has
        # already told every client so.
        if run_task is None or run_task.done():
            return
        run_task.cancel()

    async def on_run_cancelled(self, run_input: RunAgentInput) -> None:
        """Close a cancelled run, so every client watching it agrees it has ended.

        AG-UI has no event for a run that was stopped. A cancelled run did not
        produce what it was asked for, so it ends as ``RUN_ERROR`` rather than as a
        ``RUN_FINISHED`` that a client would read as success.
        """
        await self.emit(
            RunErrorEvent(type=EventType.RUN_ERROR, message="Run cancelled.")
        )

    async def on_run_refused(
        self, run_input: RunAgentInput, active_run_id: str
    ) -> None:
        """Turn away a run while the thread already has one in flight.

        Answers the asking connection alone, never the thread: the run in flight is
        unaffected, and broadcasting this would tell every other client watching it
        that it had failed.
        """
        await self.send_run_event(
            RunErrorEvent(
                type=EventType.RUN_ERROR,
                message=f"Thread is already running {active_run_id}.",
            ),
            seq=None,
        )

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
