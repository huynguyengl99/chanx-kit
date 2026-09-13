# pydantic-ai-ag-ui

Run a [Pydantic AI](https://ai.pydantic.dev) agent over the
[AG-UI protocol](https://ag-ui.com) on a chanx websocket.

```bash
copit add @chanx-kit/pydantic-ai-ag-ui
```

Builds on the [`ag-ui`](https://huynguyengl99.github.io/chanx-kit/kits/ag-ui/) kit,
which carries the protocol. This kit supplies the agent, the conversation, and the
approval round trip.

Pydantic AI speaks AG-UI itself, so this kit passes its stream through whole via
`run_events`. A paused run reports itself through `RUN_FINISHED`, whose outcome
carries the approval request, so a synthesised one would discard it.

## Use it

Point a topic at an agent and list it on a consumer:

```python
from pydantic_ai import Agent, DeferredToolRequests
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

from .ws_kits.ag_ui import AgUiEventMessage
from .ws_kits.pydantic_ai_ag_ui import PydanticAIAgUiTopic

agent = Agent("openai:gpt-5", output_type=[str, DeferredToolRequests])


class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent


class AgentConsumer(AsyncJsonWebsocketConsumer[AgUiEventMessage]):
    channel_layer_alias = "default"
    topics = [TaskletTopic]
```

A client subscribes to `agui:thread:<thread_id>` and sends `ag_ui_run`. Streamed
text, tool calls and thinking all arrive as AG-UI events, so an AG-UI frontend needs
no changes.

## Approvals, without a protocol of your own

Mark a tool `requires_approval=True` and the run pauses by itself:

```python
@agent.tool_plain(requires_approval=True)
def delete_task(task_id: str) -> str:
    ...
```

The paused run ends with `RUN_FINISHED` carrying an
[interrupt](https://docs.ag-ui.com/concepts/interrupts) — the tool call, a prompt,
and the JSON schema of the answer it expects. The client resumes by sending another
`ag_ui_run` with a `resume` entry:

```json
{
  "action": "ag_ui_run",
  "payload": {
    "threadId": "t1",
    "runId": "run-2",
    "messages": [],
    "resume": [
      {"interruptId": "int-call-1", "status": "resolved", "payload": {"approved": true}}
    ]
  }
}
```

Approval is **deny-by-default**: only an explicit `approved: true` runs the tool.
Because the interrupt id travels to every connection on the thread, any tab can
answer it, and the server keeps no pending-approval state of its own.

## The conversation stays here

AG-UI has the client send the whole message list with every run. This kit keeps the
conversation server-side instead, so `messages` carries only the new turn — which is
what makes a resumed approval work with `"messages": []`.

Persistence comes from the
[`conversation-store`](https://huynguyengl99.github.io/chanx-kit/kits/conversation-store/)
kit, which holds an opaque string so one backend serves every agent framework. This kit
converts at the edge with `ModelMessagesTypeAdapter`.

!!! warning
    The default `InMemoryConversationStore` is process-local and not durable.
    Implement `ConversationStore` against your database before running this anywhere
    real.

```python
class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent
    conversation_store = PostgresConversationStore()
```

On subscribe the topic sends the conversation back as AG-UI's `MESSAGES_SNAPSHOT`,
converted by the same adapter that writes the live stream — so a reload renders the
prompts, tool cards and answers it had before, with no replay protocol of its own.
Set `send_transcript = False` for a client that keeps its own messages.

Anything else a connection needs goes in `send_initial_state`, the `ag-ui` kit's hook,
which runs before the run in flight is replayed:

```python
class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent

    async def send_initial_state(self) -> None:
        await super().send_initial_state()
        await self.send_run_event(await self.task_state(), seq=None)
```

To hand ownership back to the client instead, override `load_history` to return `[]`
and let `run_input.messages` be the whole conversation.

## State and dependencies

Return a `StateDeps` from `agent_deps` and AG-UI's `state` is applied to it before
the run, so tools read it through `RunContext`:

```python
from pydantic_ai.ui import StateDeps


class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent

    def agent_deps(self, run_input):
        return StateDeps(TaskletState())
```

Anything that is not a `StateDeps` (or another `StateHandler`) leaves `state` alone.
Use the same hook for per-connection dependencies: the authenticated user, a tenant
id, the thread id.

## Several tabs on one agent

Set `broadcast_run_events` from the `ag-ui` kit and every connection on the thread
watches the run, including one that joins part-way through:

```python
class TaskletTopic(PydanticAIAgUiTopic):
    agent = agent
    broadcast_run_events = True
```

See [that kit's README](https://huynguyengl99.github.io/chanx-kit/kits/ag-ui/) for
what the client owes you in return.

## Customise

| Hook | Default | Purpose |
|---|---|---|
| `agent` | `None` | The agent to run |
| `get_agent()` | returns `agent` | Choose an agent per connection |
| `agent_deps(run_input)` | `None` | Dependencies, and AG-UI `state` binding |
| `load_history(run_input=None)` | from `conversation_store` | The conversation, for a run or for the transcript |
| `transcript()` | `MESSAGES_SNAPSHOT` | The conversation as AG-UI messages |
| `save_history(messages)` | to `conversation_store` | Where the conversation is written |
| `on_run_complete(result)` | saves history | React to a finished or paused run |
| `conversation_store` | `InMemoryConversationStore()` | Conversation persistence |
