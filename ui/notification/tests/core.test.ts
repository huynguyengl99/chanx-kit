import { defineChannel, defineTopic } from '@chanx-js/client';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { makeClient, open, reset } from '../../tests/harness';
import type { ContractToClient, ContractToServer } from '../contract';
import { connectNotifications, createNotificationFeed } from '../core';

const userTopic = defineTopic<ContractToServer, ContractToClient>()({
  name: 'user_notification_topic',
  pattern: 'notification:user:{user_id}',
});
const everyone = defineTopic<ContractToServer, ContractToClient>()({
  name: 'broadcast_notification_topic',
  pattern: 'notification:all',
});
const notifications = defineChannel<never, never>()({
  name: 'notifications',
  address: '/ws/notifications',
  topics: { userTopic, everyone },
});

const mine = userTopic.with({ user_id: 'ana' });
const all = everyone.with();

beforeEach(reset);

function notify(topic: string, id: string, title = id) {
  return { topic, action: 'notification', payload: { id, title } };
}

describe('createNotificationFeed', () => {
  it('keeps the newest first, up to the limit', () => {
    const feed = createNotificationFeed({ limit: 2 });
    const on = feed.on.notification as (message: any, envelope: any) => void;
    for (const id of ['a', 'b', 'c']) on({ action: 'notification', payload: { id, title: id } }, { topic: 't' });

    expect(feed.getSnapshot().items.map((item) => item.id)).toEqual(['c', 'b']);
  });

  it('notifies subscribers and stops after unsubscribing', () => {
    const feed = createNotificationFeed();
    const listener = vi.fn();
    const unsubscribe = feed.subscribe(listener);
    feed.dismiss('x');
    unsubscribe();
    feed.dismiss('x');
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe('connectNotifications', () => {
  function connect() {
    const connection = connectNotifications(makeClient(), notifications, { topics: [mine, all] });
    connection.start();
    return { connection, socket: open() };
  }

  it('collects notifications from every joined topic', () => {
    const { connection, socket } = connect();
    socket.receive(notify(mine.topic, '1', 'Just you'));
    socket.receive(notify(all.topic, '2', 'Everyone'));

    const items = connection.feed.getSnapshot().items;
    expect(items.map((item) => [item.title, item.topic])).toEqual([
      ['Everyone', 'notification:all'],
      ['Just you', 'notification:user:ana'],
    ]);
  });

  it('shows a notification sent to two topics once', () => {
    const { connection, socket } = connect();
    socket.receive(notify(mine.topic, 'same'));
    socket.receive(notify(all.topic, 'same'));
    expect(connection.feed.getSnapshot().items).toHaveLength(1);
  });

  it('acks per topic and clears', () => {
    const { connection, socket } = connect();
    socket.receive(notify(mine.topic, '1'));
    socket.receive(notify(all.topic, '2'));
    socket.receive(notify(mine.topic, '3'));

    connection.ackAll();

    expect(socket.sentOn(mine.topic).map((frame) => frame.payload)).toEqual([{ ids: ['3', '1'] }]);
    expect(socket.sentOn(all.topic).map((frame) => frame.payload)).toEqual([{ ids: ['2'] }]);
    expect(connection.feed.getSnapshot().items).toEqual([]);
  });

  it('dismisses one without acking it', () => {
    const { connection, socket } = connect();
    socket.receive(notify(mine.topic, '1'));
    connection.feed.dismiss('1');
    expect(connection.feed.getSnapshot().items).toEqual([]);
    expect(socket.sentOn(mine.topic)).toEqual([]);
  });
});

describe('contract fit (checked by tsc)', () => {
  it('accepts a topic that sends more than the contract, and rejects one that does not speak it', () => {
    type Extra = { action: 'notification_badge'; payload: { count: number } };
    const wider = defineTopic<ContractToServer, ContractToClient | Extra>()({ name: 'w', pattern: 'w' });
    const other = defineTopic<ContractToServer, { action: 'notification'; payload: { nope: 1 } }>()({
      name: 'o',
      pattern: 'o',
    });
    const channel = defineChannel<never, never>()({ name: 'c', address: '/c', topics: { wider, other } });

    connectNotifications(makeClient(), channel, { topics: [wider.with()] });
    // @ts-expect-error its `notification` payload is not the contract's
    connectNotifications(makeClient(), channel, { topics: [other.with()] });
  });
});
