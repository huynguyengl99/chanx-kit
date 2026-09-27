# AG-UI thread

Headless state for one AG-UI conversation over a thread topic, for any server
speaking **ag-ui@1**, such as the `ag-ui` or `pydantic-ai-ag-ui` server kits. It
folds streamed events into AG-UI messages, tracks the run in flight, and sends
`ag_ui_run` / `ag_ui_cancel`. There is no component: chat UIs are app-specific, so
render `messages` your way.

```bash
copit add @chanx-kit-ui/ag-ui
```

## React

```tsx
import { useAgentThread } from '@/chanx-kit/ag-ui/react';
import { agent } from '@/generated';

export function Conversation({ threadId }: { threadId: string }) {
  const { messages, running, error, run, cancel } = useAgentThread(
    agent,
    agent.topics.agentTopic.with({ thread_id: threadId }),
  );
  // messages are AG-UI Message objects: role, content, toolCalls.
}
```

## What it handles

- **Messages**: text (`TEXT_MESSAGE_*`, `TEXT_MESSAGE_CHUNK`), tool calls on the
  assistant message (`TOOL_CALL_*`), results as `tool` messages, and
  `MESSAGES_SNAPSHOT`, which replaces the conversation.
- **Runs**: `running`, `runId` and `error`. A refusal (the thread is busy with another
  tab's run) sets `error` without ending that run.
- **Replay**: with `broadcast_run_events`, a joining or reconnecting tab is replayed the
  run from its start. Events carry `seq`, and the ones already applied are skipped.
- **Everything else** (`STATE_DELTA`, `CUSTOM`, steps) reaches `onEvent`, after
  `STATE_SNAPSHOT` has been kept as `state`.

`run(text, input)` sends the whole conversation, as AG-UI expects; pass `tools`,
`context` or `forwardedProps` in `input`.

## Without a framework

```ts
import { connectAgentThread } from '@/chanx-kit/ag-ui';

const chat = connectAgentThread(client, agent, agent.topics.agentTopic.with({ thread_id: 't1' }));
chat.thread.subscribe(() => render(chat.thread.getSnapshot()));
chat.start();
chat.run('Hello');
```
