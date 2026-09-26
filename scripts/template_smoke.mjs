#!/usr/bin/env node
// Smoke-test a running project from templates/fastapi-react through chanx-js.
//
//   node scripts/template_smoke.mjs <project-dir> [http://127.0.0.1:8000]

import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const project = resolve(process.argv[2] ?? 'templates/fastapi-react');
const base = process.argv[3] ?? 'http://127.0.0.1:8000';

const { createClient, createTopicsController, defineChannel, defineTopic } = await import(
  pathToFileURL(join(project, 'web/node_modules/@chanx-js/client/dist/index.mjs')).href
);

// Mirrors web/src/generated/channels.ts.
const notifications = defineChannel()({
  name: 'notifications',
  address: '/ws/notifications',
  heartbeat: true,
  topics: {
    user: defineTopic()({ name: 'app_user_notification_topic', pattern: 'notification:user:{user_id}' }),
    all: defineTopic()({ name: 'broadcast_notification_topic', pattern: 'notification:all' }),
  },
});

const received = [];
const refused = [];
const acked = [];
let waiters = [];

function settle() {
  waiters = waiters.filter(({ check, done }) => !(check() && (done(), true)));
}

function waitFor(what, check, ms = 5000) {
  return new Promise((done, fail) => {
    const timer = setTimeout(() => fail(new Error(`timed out waiting for ${what}`)), ms);
    waiters.push({ check, done: () => (clearTimeout(timer), done()) });
    settle();
  });
}

async function notify(body) {
  const response = await fetch(`${base}/api/notify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`POST /api/notify: ${response.status}`);
}

const client = createClient({ baseUrl: base.replace(/^http/, 'ws') });
const mine = notifications.topics.user.with({ user_id: 'ana' });
const everyone = notifications.topics.all.with();
const theirs = notifications.topics.user.with({ user_id: 'bob' });

const controller = createTopicsController(client, notifications, {
  queryParams: { as: 'ana' },
  topics: [mine, everyone, theirs],
  buffer: 'none',
  on: {
    notification: (message, { topic }) => (received.push({ topic, ...message.payload }), settle()),
    notification_acked: (message) => (acked.push(...message.payload.ids), settle()),
  },
  onSubscribeError: (topic) => (refused.push(topic), settle()),
});
controller.subscribe(settle);
controller.start();

try {
  await waitFor('both topics joined', () => {
    const { subscribed } = controller.getSnapshot();
    return subscribed.includes(mine.topic) && subscribed.includes(everyone.topic);
  });
  await waitFor("bob's topic refused", () => refused.includes(theirs.topic));

  await notify({ title: 'to everyone' });
  await waitFor('the broadcast', () => received.some((n) => n.topic === everyone.topic));

  await notify({ title: 'to ana', user: 'ana' });
  await waitFor("ana's notification", () => received.some((n) => n.topic === mine.topic));

  const id = received.find((n) => n.topic === mine.topic).id;
  controller.sendTopic(mine.topic, { action: 'notification_ack', payload: { ids: [id] } });
  await waitFor('the ack', () => acked.includes(id));

  console.log(`ok: ${received.length} notifications, ack confirmed, other user refused`);
} catch (error) {
  console.error(`fail: ${error.message}`);
  console.error({ snapshot: controller.getSnapshot(), received, refused, acked });
  process.exitCode = 1;
} finally {
  controller.stop();
  client.terminate?.();
  setTimeout(() => process.exit(), 100);
}
