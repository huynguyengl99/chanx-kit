import { useState } from 'react';

import { NotificationFeed, useNotifications } from '@/chanx-kit/notification';
import { notifications } from '@/generated';

const everyone = notifications.topics.broadcastNotificationTopic.with();

export function App() {
  const [who, setWho] = useState('ana');

  // One socket, two topics; the server authorizes each subscription.
  const mine = notifications.topics.appUserNotificationTopic.with({ user_id: who });
  const { items, status, ackAll } = useNotifications(notifications, {
    queryParams: { as: who },
    topics: [mine, everyone],
  });

  return (
    <main>
      <header>
        <h1>chanx app</h1>
        <p>
          A FastAPI backend with the <code>notification</code> kit, and a React client
          generated from the server&apos;s AsyncAPI schema. Open a second tab to see a
          broadcast reach both.
        </p>
        <label>
          Connect as
          <input value={who} onChange={(event) => setWho(event.target.value)} />
        </label>
      </header>

      <div className="grid">
        <NotificationFeed
          items={items}
          status={status}
          onAckAll={ackAll}
          describeTopic={(topic) => (topic === everyone.topic ? 'everyone' : 'just you')}
        />
        <SendForm who={who} />
      </div>
    </main>
  );
}

/** Sends through `POST /api/notify`; the server pushes over the socket. */
function SendForm({ who }: { who: string }) {
  const [title, setTitle] = useState('Hello');
  const [justMe, setJustMe] = useState(false);

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    await fetch('/api/notify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, user: justMe ? who : null }),
    });
  };

  return (
    <form className="panel" onSubmit={send}>
      <h2>Send one</h2>
      <p className="hint">
        Posts to <code>/api/notify</code>, which calls the kit&apos;s topic class. No
        WebSocket involved on the sending side.
      </p>
      <input value={title} onChange={(event) => setTitle(event.target.value)} />
      <label>
        <input
          type="checkbox"
          checked={justMe}
          onChange={(event) => setJustMe(event.target.checked)}
        />
        Only to {who || 'this user'}
      </label>
      <button type="submit">Send</button>
      <p className="hint">
        From another process: <code>python -m app.notify "Build finished"</code> (needs{' '}
        <code>REDIS_URL</code>, see the README).
      </p>
    </form>
  );
}
