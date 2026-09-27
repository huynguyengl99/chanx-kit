import { defineChannel, defineTopic } from '@chanx-js/client';
import { beforeEach, describe, expect, it } from 'vitest';

import { makeClient, open, reset } from '../../tests/harness';
import type { ContractToClient, ContractToServer } from '../contract';
import { connectChat } from '../core';

const chatTopic = defineTopic<ContractToServer, ContractToClient>()({ name: 'chat_topic', pattern: 'chat:{room}' });
const room = defineChannel<never, never>()({ name: 'room', address: '/ws/rooms/{room}', topics: { chatTopic } });
const lobby = chatTopic.with({ room: 'lobby' });

beforeEach(reset);

function connect() {
  const connection = connectChat(makeClient(), room, lobby, { params: { room: 'lobby' } });
  connection.start();
  return { connection, socket: open() };
}

const entry = (id: string, at: string) => ({ id, body: id, room: 'lobby', author: { id: 'ana' }, sent_at: at });
const bodies = (connection: ReturnType<typeof connect>['connection']) =>
  connection.log.getSnapshot().entries.map((e) => e.body);

describe('connectChat', () => {
  it('starts from the backlog and appends live messages', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: lobby.topic, action: 'chat_backlog', payload: { room: 'lobby', entries: [entry('a', '1')] } });
    socket.receive({ topic: lobby.topic, action: 'chat_message', payload: entry('b', '2') });
    expect(bodies(connection)).toEqual(['a', 'b']);
  });

  it('ignores a message it already has', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: lobby.topic, action: 'chat_message', payload: entry('a', '1') });
    socket.receive({ topic: lobby.topic, action: 'chat_message', payload: entry('a', '1') });
    expect(bodies(connection)).toEqual(['a']);
  });

  it('keeps live messages newer than a backlog that arrives after them', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: lobby.topic, action: 'chat_message', payload: entry('c', '3') });
    socket.receive({
      topic: lobby.topic,
      action: 'chat_backlog',
      payload: { room: 'lobby', entries: [entry('a', '1'), entry('b', '2')] },
    });
    expect(bodies(connection)).toEqual(['a', 'b', 'c']);
  });

  it('posts and requests history on the topic', () => {
    const { connection, socket } = connect();
    connection.send('hi');
    connection.requestBacklog(10);
    expect(socket.sentOn(lobby.topic).map(({ action, payload }) => [action, payload])).toEqual([
      ['chat_send', { body: 'hi' }],
      ['chat_backlog_request', { limit: 10 }],
    ]);
  });
});
