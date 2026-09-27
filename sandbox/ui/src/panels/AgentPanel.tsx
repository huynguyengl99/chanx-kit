import { useRef, useState } from 'react';

import { useAgentThread } from '../chanx-kit/ag-ui/react';
import { agent } from '../generated';

/** ag-ui kit through the headless ag-ui UI kit; the markup is the app's own. */
export function AgentPanel() {
  const [prompt, setPrompt] = useState('Explain AG-UI in one sentence.');
  const [lastEvent, setLastEvent] = useState('');
  const threadId = useRef(crypto.randomUUID());

  // A thread is the topic, so several conversations could share this connection.
  const { messages, running, error, status, run, cancel } = useAgentThread(
    agent,
    agent.topics.demoAgUiTopic.with({ thread_id: threadId.current }),
    { onEvent: (event) => setLastEvent(event.type) },
  );

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Agent · AG-UI</h2>
        <span className="status" data-state={status}>
          {status}
        </span>
      </div>

      <ul className="log">
        {messages.length === 0 && <li>Run something to see AG-UI events arrive.</li>}
        {messages.map((message) => (
          <li key={message.id}>
            <span className="who">{message.role}</span>{' '}
            {typeof message.content === 'string' ? message.content : ''}
          </li>
        ))}
        {error && <li className="error">{error}</li>}
      </ul>

      <div className="row">
        <textarea rows={2} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
      </div>
      <div className="row">
        <button onClick={() => run(prompt)} disabled={status !== 'open' || running}>
          {running ? 'Running…' : 'Run'}
        </button>
        {running && (
          <button className="ghost" onClick={cancel}>
            Stop
          </button>
        )}
        {lastEvent && <span className="chip">last event: {lastEvent}</span>}
      </div>
      <p className="hint">
        Every message is one <code>ag_ui_event</code>, switched on the protocol&apos;s own{' '}
        <code>type</code>, so an AG-UI frontend needs no adapter.
      </p>
    </section>
  );
}
