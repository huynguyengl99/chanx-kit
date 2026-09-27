import type {
  AddressOf,
  ChanxClient,
  ChannelDescriptor,
  ChanxMessage,
  Envelope,
  HandlerMap,
  TopicControllerOptions,
  TopicRef,
  TopicRefOf,
} from '@chanx-js/client';
import { createTopicController } from '@chanx-js/client';

import type {
  AgUiEventMessage,
  AssistantMessage,
  ContractToClient,
  ContractToServer,
  RunAgentInput,
} from './contract';

/** A topic whose messages fit ag-ui@1; extra actions are fine. */
export type AgUiThreadTopic<Ref> =
  Ref extends TopicRef<infer ToServer, infer ToClient, any>
    ? [ContractToServer] extends [ToServer]
      ? [Extract<ToClient, { action: ContractToClient['action'] }>] extends [ContractToClient]
        ? Ref
        : never
      : never
    : never;

export type AgUiEvent = AgUiEventMessage['payload'];
export type AgUiMessage = RunAgentInput['messages'][number];

export interface AgentThreadSnapshot {
  /** AG-UI messages, so they go back unchanged as the next run's input. */
  messages: AgUiMessage[];
  /** The run in flight, if any. */
  runId: string | null;
  running: boolean;
  /** The last run's error, cleared when the next run starts. */
  error: string | null;
  /** The latest `STATE_SNAPSHOT`. `STATE_DELTA` reaches `onEvent` only. */
  state: unknown;
}

export interface AgentThreadOptions {
  threadId: string;
  /** Every event, after it is applied: for `STATE_DELTA`, `CUSTOM` and the like. */
  onEvent?: (event: AgUiEvent) => void;
  newId?: () => string;
}

export type SendToThread = (message: ContractToServer) => void;

export interface AgentThread {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => AgentThreadSnapshot;
  /** Handlers to pass as `on` to a topic controller or `useTopic`. */
  on: HandlerMap<ContractToClient>;
  /** Apply one event; `seq` is the envelope's, when the server broadcasts the run. */
  apply: (event: AgUiEvent, seq?: number) => void;
  /** Add a user message and run the agent on the whole conversation. */
  run: (send: SendToThread, text: string, input?: Partial<RunAgentInput>) => string;
  /** Ask the server to stop the run in flight. */
  cancel: (send: SendToThread) => void;
}

export function createAgentThread({
  threadId,
  onEvent,
  newId = () => crypto.randomUUID(),
}: AgentThreadOptions): AgentThread {
  const listeners = new Set<() => void>();
  let snapshot: AgentThreadSnapshot = { messages: [], runId: null, running: false, error: null, state: undefined };
  // A rejoining tab is replayed the run from seq 1; skip what was already applied.
  let lastSeq = 0;

  const publish = (next: Partial<AgentThreadSnapshot>) => {
    snapshot = { ...snapshot, ...next };
    for (const listener of [...listeners]) listener();
  };

  const upsert = (id: string, update: (message: AgUiMessage | undefined) => AgUiMessage) => {
    const index = snapshot.messages.findIndex((message) => message.id === id);
    const messages = [...snapshot.messages];
    if (index === -1) messages.push(update(undefined));
    else messages[index] = update(messages[index]);
    publish({ messages });
  };

  const appendText = (id: string, delta: string) =>
    upsert(id, (message) =>
      message && 'content' in message && typeof message.content !== 'object'
        ? ({ ...message, content: (message.content ?? '') + delta } as AgUiMessage)
        : { id, role: 'assistant', content: delta },
    );

  const assistantFor = (toolCallId: string, parentId?: string | null): string => {
    if (parentId) return parentId;
    const last = snapshot.messages.at(-1);
    return last?.role === 'assistant' ? last.id : toolCallId;
  };

  const toolCallParent = (toolCallId: string) =>
    snapshot.messages.find(
      (message): message is AssistantMessage =>
        message.role === 'assistant' && !!message.toolCalls?.some((call) => call.id === toolCallId),
    );

  const startToolCall = (toolCallId: string, name: string, parentId?: string | null) =>
    upsert(assistantFor(toolCallId, parentId), (message) => {
      const assistant = (message ?? { id: assistantFor(toolCallId, parentId), role: 'assistant' }) as AssistantMessage;
      if (assistant.toolCalls?.some((call) => call.id === toolCallId)) return assistant;
      const call = { id: toolCallId, type: 'function' as const, function: { name, arguments: '' } };
      return { ...assistant, toolCalls: [...(assistant.toolCalls ?? []), call] };
    });

  const appendArgs = (toolCallId: string, delta: string) => {
    const parent = toolCallParent(toolCallId);
    if (!parent) return;
    upsert(parent.id, () => ({
      ...parent,
      toolCalls: parent.toolCalls?.map((call) =>
        call.id === toolCallId ? { ...call, function: { ...call.function, arguments: call.function.arguments + delta } } : call,
      ),
    }));
  };

  const apply = (event: AgUiEvent, seq?: number) => {
    if (seq !== undefined) {
      const replayedStart = event.type === 'RUN_STARTED' && event.runId === snapshot.runId;
      if ((event.type !== 'RUN_STARTED' || replayedStart) && seq <= lastSeq) return;
      if (event.type === 'RUN_STARTED' && !replayedStart) lastSeq = 0;
      lastSeq = Math.max(lastSeq, seq);
    }

    switch (event.type) {
      case 'RUN_STARTED':
        publish({ runId: event.runId, running: true, error: null });
        break;
      case 'RUN_FINISHED':
        publish({ runId: null, running: false });
        break;
      case 'RUN_ERROR':
        // A seq-less refusal goes to the asking tab only; the thread's run carries on.
        if (seq === undefined && lastSeq > 0 && snapshot.running) publish({ error: event.message });
        else publish({ runId: null, running: false, error: event.message });
        break;
      case 'TEXT_MESSAGE_START':
        upsert(event.messageId, (message) => message ?? { id: event.messageId, role: event.role ?? 'assistant', content: '' } as AgUiMessage);
        break;
      case 'TEXT_MESSAGE_CONTENT':
        appendText(event.messageId, event.delta);
        break;
      case 'TEXT_MESSAGE_CHUNK': {
        const id = event.messageId ?? snapshot.messages.at(-1)?.id ?? newId();
        appendText(id, event.delta ?? '');
        break;
      }
      case 'TOOL_CALL_START':
        startToolCall(event.toolCallId, event.toolCallName, event.parentMessageId);
        break;
      case 'TOOL_CALL_ARGS':
        appendArgs(event.toolCallId, event.delta);
        break;
      case 'TOOL_CALL_CHUNK':
        if (!event.toolCallId) break;
        if (!toolCallParent(event.toolCallId)) startToolCall(event.toolCallId, event.toolCallName ?? '', event.parentMessageId);
        appendArgs(event.toolCallId, event.delta ?? '');
        break;
      case 'TOOL_CALL_RESULT':
        upsert(event.messageId, () => ({
          id: event.messageId,
          role: 'tool',
          content: event.content,
          toolCallId: event.toolCallId,
        }));
        break;
      case 'MESSAGES_SNAPSHOT':
        publish({ messages: event.messages });
        break;
      case 'STATE_SNAPSHOT':
        publish({ state: event.snapshot });
        break;
    }
    onEvent?.(event);
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    on: {
      ag_ui_event: (message: AgUiEventMessage, envelope: Envelope) => apply(message.payload, envelope.seq),
    },
    apply,
    run(send, text, input = {}) {
      const runId = input.runId ?? newId();
      const messages: AgUiMessage[] = [...snapshot.messages, { id: newId(), role: 'user', content: text }];
      publish({ messages, error: null });
      send({
        action: 'ag_ui_run',
        payload: {
          threadId,
          state: snapshot.state ?? {},
          tools: [],
          context: [],
          forwardedProps: {},
          ...input,
          runId,
          messages,
        },
      });
      return runId;
    },
    cancel(send) {
      if (snapshot.runId) send({ action: 'ag_ui_cancel', payload: { runId: snapshot.runId } });
    },
  };
}

export type ConnectAgentThreadOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
> &
  Omit<AgentThreadOptions, 'threadId'> & { threadId?: string };

/** Join an AG-UI thread topic without a framework. Call `start()`, then read `thread`. */
export function connectAgentThread<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  client: ChanxClient,
  channel: D,
  topic: Ref & AgUiThreadTopic<Ref>,
  { threadId, onEvent, newId, ...options }: ConnectAgentThreadOptions<D> = {},
) {
  const thread = createAgentThread({
    threadId: threadId ?? String((topic as TopicRef).params.thread_id ?? ''),
    onEvent,
    newId,
  });
  const controller = createTopicController(client, channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: thread.on as HandlerMap<ChanxMessage>,
  });
  const send: SendToThread = (message) => controller.send(message);
  return {
    thread,
    controller,
    run: (text: string, input?: Partial<RunAgentInput>) => thread.run(send, text, input),
    cancel: () => thread.cancel(send),
    start: () => controller.start(),
    stop: () => controller.stop(),
  };
}
