"""Pydantic AI agents served over the AG-UI protocol."""

from collections.abc import AsyncIterator, Sequence
from typing import Any, ClassVar, cast

from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.agent import AbstractAgent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.run import AgentRunResult
from pydantic_ai.ui.ag_ui import AGUIAdapter

from ag_ui.core import Event, EventType, MessagesSnapshotEvent, RunAgentInput

from ..ag_ui.topics import AgUiTopic
from ..conversation_store.store import ConversationStore, InMemoryConversationStore


class PydanticAIAgUiTopic(AgUiTopic):
    """Run a Pydantic AI agent for one thread: ``agui:thread:<thread_id>``. Set
    :attr:`agent`, and streaming, tool calls and approvals all arrive as AG-UI
    events."""

    agent: ClassVar[AbstractAgent[Any, Any] | None] = None

    conversation_store: ClassVar[ConversationStore] = InMemoryConversationStore()

    def get_agent(self) -> AbstractAgent[Any, Any]:
        """The agent this run uses. Override to choose one per connection."""
        if self.agent is None:
            raise NotImplementedError(
                f"{type(self).__name__} must set `agent`, or override get_agent(), "
                "to run a Pydantic AI agent."
            )
        return self.agent

    def agent_deps(self, run_input: RunAgentInput) -> Any:
        """Dependencies for this run. Return a
        [`StateDeps`][pydantic_ai.ui.StateDeps] to receive AG-UI's ``state``."""
        return None

    async def load_history(
        self, run_input: RunAgentInput | None = None
    ) -> list[ModelMessage]:
        """The stored conversation. ``run_input`` is passed when a run is about to
        use it, and omitted when something else needs it, such as the transcript
        sent on subscribe."""
        conversation = await self.conversation_store.load(self.thread_id)
        return (
            ModelMessagesTypeAdapter.validate_json(conversation) if conversation else []
        )

    async def save_history(self, messages: Sequence[ModelMessage]) -> None:
        conversation = ModelMessagesTypeAdapter.dump_json(list(messages)).decode()
        await self.conversation_store.save(self.thread_id, conversation)

    async def transcript(self) -> MessagesSnapshotEvent | None:
        """The stored conversation as AG-UI messages.

        The adapter that writes the live stream also knows how to dump stored
        messages into it, so a reload needs no replay protocol of its own. The
        kit sends this before replaying the run in flight.
        """
        messages = await self.load_history()
        if not messages:
            return None
        return MessagesSnapshotEvent(
            type=EventType.MESSAGES_SNAPSHOT,
            messages=AGUIAdapter.dump_messages(messages),
        )

    async def on_run_complete(self, result: AgentRunResult[Any]) -> None:
        """Persist the conversation. Also runs when a run stops for approval, which
        is what lets the resumed run continue from where it paused."""
        await self.save_history(result.all_messages())

    async def run_events(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        adapter = AGUIAdapter(agent=self.get_agent(), run_input=run_input)
        # run_stream reads the client's `resume` entries itself, so resolving an
        # approval needs no pending state on the server.
        async for event in adapter.run_stream(
            message_history=await self.load_history(run_input),
            deps=self.agent_deps(run_input),
            on_complete=self.on_run_complete,
        ):
            yield cast(Event, event)
