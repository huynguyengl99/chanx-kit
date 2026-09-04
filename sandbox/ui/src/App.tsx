import { useState } from 'react';

import { AgentPanel } from './panels/AgentPanel';
import { NotificationPanel } from './panels/NotificationPanel';
import { RoomPanel } from './panels/RoomPanel';

export function App() {
  const [who, setWho] = useState('ana');

  return (
    <main>
      <header>
        <h1>ChanX Kit</h1>
        <p>
          Every panel below is a kit from the registry, composed into a consumer in{' '}
          <code>sandbox/consumers.py</code>. The message types are generated from the
          server&apos;s own AsyncAPI schema.
        </p>
        <label>
          Connect as
          <input value={who} onChange={(event) => setWho(event.target.value)} />
        </label>
      </header>

      <div className="grid">
        <RoomPanel who={who} />
        <NotificationPanel who={who} />
        <AgentPanel />
      </div>
    </main>
  );
}
