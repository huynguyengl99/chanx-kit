import { defineChannel, defineTopic } from '@chanx-js/client';
import { beforeEach, describe, expect, it } from 'vitest';

import { makeClient, open, reset } from '../../tests/harness';
import type { ContractToClient, ContractToServer } from '../contract';
import { connectPresence } from '../core';

const presenceTopic = defineTopic<ContractToServer, ContractToClient>()({
  name: 'presence_topic',
  pattern: 'presence:{scope}',
});
const room = defineChannel<never, never>()({
  name: 'room',
  address: '/ws/rooms/{room}',
  topics: { presenceTopic },
});
const lobby = presenceTopic.with({ scope: 'lobby' });

beforeEach(reset);

function connect() {
  const connection = connectPresence(makeClient(), room, lobby, { params: { room: 'lobby' } });
  connection.start();
  return { connection, socket: open() };
}

const member = (id: string) => ({ id, name: id.toUpperCase() });
const ids = (connection: ReturnType<typeof connect>['connection']) =>
  connection.roster.getSnapshot().members.map((m) => m.id);

describe('connectPresence', () => {
  it('starts from the state and follows joins and leaves', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: lobby.topic, action: 'presence_state', payload: { scope: 'lobby', members: [member('ana')] } });
    socket.receive({ topic: lobby.topic, action: 'presence_join', payload: { scope: 'lobby', member: member('bo') } });
    expect(ids(connection)).toEqual(['ana', 'bo']);

    socket.receive({ topic: lobby.topic, action: 'presence_leave', payload: { scope: 'lobby', member: member('ana') } });
    expect(ids(connection)).toEqual(['bo']);
  });

  it('does not list someone twice when a join repeats', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: lobby.topic, action: 'presence_join', payload: { scope: 'lobby', member: member('bo') } });
    socket.receive({ topic: lobby.topic, action: 'presence_join', payload: { scope: 'lobby', member: member('bo') } });
    expect(ids(connection)).toEqual(['bo']);
  });

  it('replaces the roster when the state is sent again, as after a reconnect', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: lobby.topic, action: 'presence_join', payload: { scope: 'lobby', member: member('gone') } });
    socket.receive({ topic: lobby.topic, action: 'presence_state', payload: { scope: 'lobby', members: [member('ana')] } });
    expect(ids(connection)).toEqual(['ana']);
  });

  it('asks for the roster again on refresh', () => {
    const { connection, socket } = connect();
    connection.refresh();
    expect(socket.sentOn(lobby.topic).map((frame) => frame.action)).toEqual(['presence_request']);
  });
});
