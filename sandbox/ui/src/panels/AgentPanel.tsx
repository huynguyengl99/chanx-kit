import { useRef, useState } from 'react';

import type {
  AgentDemoAgUiTopicToClient,
  AgentDemoAgUiTopicToServer,
} from '../generated';
import { useTopics } from '../lib/socket';

/**
 * ag-ui kit: the AG-UI protocol over a websocket.
 *
 * Everything arrives as one `ag_ui_event` action and the protocol's own `type` field
 * discriminates — which is what an AG-UI client already does over SSE, so this handler
 * would port to any AG-UI transport unchanged.
 */
export function AgentPanel() {
  const [prompt, setPrompt] = useState('Explain AG-UI in one sentence.');
  const [answer, setAnswer] = useState('');
  const [running, setRunning] = useState(false);
  const [lastEvent, setLastEvent] = useState('');
  const threadId = useRef(crypto.randomUUID());
  // A thread is the topic, so several conversations could share this connection.
  const topic = `agui:thread:${threadId.current}`;

  const { send, status } = useTopics<
    AgentDemoAgUiTopicToClient,
    AgentDemoAgUiTopicToServer
  >(
    '/ws/agent',
    [topic],
    (message) => {
      if (message.action !== 'ag_ui_event') return;

      const event = message.payload;
      setLastEvent(event.type);

      switch (event.type) {
        case 'RUN_STARTED':
          setAnswer('');
          setRunning(true);
          break;
        case 'TEXT_MESSAGE_CONTENT':
          setAnswer((current) => current + event.delta);
          break;
        case 'RUN_ERROR':
          setAnswer(`Error: ${event.message}`);
          setRunning(false);
          break;
        case 'RUN_FINISHED':
          setRunning(false);
          break;
      }
    },
  );

  const ask = () => {
    send(topic, {
      action: 'ag_ui_run',
      payload: {
        threadId: threadId.current,
        runId: crypto.randomUUID(),
        state: {},
        messages: [{ id: crypto.randomUUID(), role: 'user', content: prompt }],
        tools: [],
        context: [],
        forwardedProps: {},
      },
    });
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Agent · AG-UI</h2>
        <span className="status" data-state={status}>
          {status}
        </span>
      </div>

      <div className="answer">{answer || 'Run something to see AG-UI events arrive.'}</div>

      <div className="row">
        <textarea rows={2} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
      </div>
      <div className="row">
        <button onClick={ask} disabled={status !== 'open' || running}>
          {running ? 'Running…' : 'Run'}
        </button>
        {lastEvent && <span className="chip">last event: {lastEvent}</span>}
      </div>
      <p className="hint">
        Every message is one <code>ag_ui_event</code>, switched on the protocol&apos;s own{' '}
        <code>type</code> — so an AG-UI frontend needs no adapter.
      </p>
    </section>
  );
}
