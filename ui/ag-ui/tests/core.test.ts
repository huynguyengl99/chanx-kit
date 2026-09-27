import { defineChannel, defineTopic } from '@chanx-js/client';
import { beforeEach, describe, expect, it } from 'vitest';

import { makeClient, open, reset } from '../../tests/harness';
import type { ContractToClient, ContractToServer } from '../contract';
import type { AgUiEvent } from '../core';
import { connectAgentThread, createAgentThread } from '../core';

const threadTopic = defineTopic<ContractToServer, ContractToClient>()({
  name: 'ag_ui_topic',
  pattern: 'agui:thread:{thread_id}',
});
const agent = defineChannel<never, never>()({ name: 'agent', address: '/ws/agent', topics: { threadTopic } });
const t1 = threadTopic.with({ thread_id: 't1' });

beforeEach(reset);

let ids = 0;
const newId = () => `id-${++ids}`;

const started = (runId = 'r1'): AgUiEvent => ({ type: 'RUN_STARTED', threadId: 't1', runId });
const finished = (runId = 'r1'): AgUiEvent => ({ type: 'RUN_FINISHED', threadId: 't1', runId });
const text = (messageId: string, delta: string): AgUiEvent[] => [
  { type: 'TEXT_MESSAGE_START', messageId, role: 'assistant' },
  { type: 'TEXT_MESSAGE_CONTENT', messageId, delta },
  { type: 'TEXT_MESSAGE_END', messageId },
];

describe('createAgentThread', () => {
  it('folds a streamed reply into one assistant message', () => {
    const thread = createAgentThread({ threadId: 't1' });
    for (const event of [started(), ...text('m1', 'Hel'), { type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: 'lo' } as AgUiEvent])
      thread.apply(event);

    expect(thread.getSnapshot().messages).toEqual([{ id: 'm1', role: 'assistant', content: 'Hello' }]);
    expect(thread.getSnapshot().running).toBe(true);

    thread.apply(finished());
    expect(thread.getSnapshot()).toMatchObject({ running: false, runId: null });
  });

  it('skips what a replay resends and applies what is new', () => {
    const thread = createAgentThread({ threadId: 't1' });
    const events = [started(), ...text('m1', 'Hi')];
    events.forEach((event, index) => thread.apply(event, index + 1));

    // The server replays the run from seq 1 after a reconnect, then carries on.
    events.forEach((event, index) => thread.apply(event, index + 1));
    thread.apply({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: '!' }, 5);

    expect(thread.getSnapshot().messages).toEqual([{ id: 'm1', role: 'assistant', content: 'Hi!' }]);
  });

  it('starts counting again for the next run', () => {
    const thread = createAgentThread({ threadId: 't1' });
    [started('r1'), ...text('m1', 'one'), finished('r1')].forEach((event, index) => thread.apply(event, index + 1));
    [started('r2'), ...text('m2', 'two')].forEach((event, index) => thread.apply(event, index + 1));

    expect(thread.getSnapshot().messages.map((m) => m.id)).toEqual(['m1', 'm2']);
    expect(thread.getSnapshot().runId).toBe('r2');
  });

  it('shows a refusal without ending the run another tab started', () => {
    const thread = createAgentThread({ threadId: 't1' });
    thread.apply(started(), 1);
    thread.apply({ type: 'RUN_ERROR', message: 'Thread is already running r1.' });

    expect(thread.getSnapshot()).toMatchObject({ running: true, runId: 'r1', error: 'Thread is already running r1.' });
  });

  it('ends the run on its own error', () => {
    const thread = createAgentThread({ threadId: 't1' });
    thread.apply(started());
    thread.apply({ type: 'RUN_ERROR', message: 'boom' });
    expect(thread.getSnapshot()).toMatchObject({ running: false, error: 'boom' });
  });

  it('records tool calls on the assistant message and results as tool messages', () => {
    const thread = createAgentThread({ threadId: 't1' });
    thread.apply({ type: 'TOOL_CALL_START', toolCallId: 'c1', toolCallName: 'weather', parentMessageId: 'm1' });
    thread.apply({ type: 'TOOL_CALL_ARGS', toolCallId: 'c1', delta: '{"city":' });
    thread.apply({ type: 'TOOL_CALL_ARGS', toolCallId: 'c1', delta: '"Hue"}' });
    thread.apply({ type: 'TOOL_CALL_END', toolCallId: 'c1' });
    thread.apply({ type: 'TOOL_CALL_RESULT', messageId: 'm2', toolCallId: 'c1', content: 'sunny' });

    expect(thread.getSnapshot().messages).toEqual([
      {
        id: 'm1',
        role: 'assistant',
        toolCalls: [{ id: 'c1', type: 'function', function: { name: 'weather', arguments: '{"city":"Hue"}' } }],
      },
      { id: 'm2', role: 'tool', content: 'sunny', toolCallId: 'c1' },
    ]);
  });

  it('replaces the conversation on a messages snapshot and keeps the state snapshot', () => {
    const seen: string[] = [];
    const thread = createAgentThread({ threadId: 't1', onEvent: (event) => seen.push(event.type) });
    thread.apply({ type: 'MESSAGES_SNAPSHOT', messages: [{ id: 'u1', role: 'user', content: 'hi' }] });
    thread.apply({ type: 'STATE_SNAPSHOT', snapshot: { step: 2 } });
    thread.apply({ type: 'STATE_DELTA', delta: [] });

    expect(thread.getSnapshot().messages).toEqual([{ id: 'u1', role: 'user', content: 'hi' }]);
    expect(thread.getSnapshot().state).toEqual({ step: 2 });
    expect(seen).toEqual(['MESSAGES_SNAPSHOT', 'STATE_SNAPSHOT', 'STATE_DELTA']);
  });
});

describe('connectAgentThread', () => {
  function connect() {
    const connection = connectAgentThread(makeClient(), agent, t1, { newId });
    connection.start();
    return { connection, socket: open() };
  }

  it('sends the whole conversation as the run input', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: t1.topic, action: 'ag_ui_event', payload: { type: 'MESSAGES_SNAPSHOT', messages: [{ id: 'u0', role: 'user', content: 'earlier' }] } });

    const runId = connection.run('now');

    const [frame] = socket.sentOn(t1.topic);
    expect(frame?.action).toBe('ag_ui_run');
    expect(frame?.payload).toMatchObject({ threadId: 't1', runId, tools: [], context: [] });
    expect(frame?.payload.messages.map((m: { content: string }) => m.content)).toEqual(['earlier', 'now']);
  });

  it('cancels the run in flight by id', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: t1.topic, action: 'ag_ui_event', seq: 1, payload: started('r9') });
    connection.cancel();
    expect(socket.sentOn(t1.topic).map((frame) => frame.payload)).toEqual([{ runId: 'r9' }]);
  });

  it('reads seq from the envelope', () => {
    const { connection, socket } = connect();
    const frames = [started(), ...text('m1', 'Hi')].map((payload, index) => ({
      topic: t1.topic,
      action: 'ag_ui_event',
      seq: index + 1,
      payload,
    }));
    frames.forEach((frame) => socket.receive(frame));
    frames.forEach((frame) => socket.receive(frame));
    expect(connection.thread.getSnapshot().messages).toEqual([{ id: 'm1', role: 'assistant', content: 'Hi' }]);
  });
});
