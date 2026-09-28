import { useEffect, useState } from 'react';

import { DEMOS, type Providers } from './demos';

const DOCS = 'https://huynguyengl99.github.io/chanx-kit';
const SOURCE = 'https://github.com/huynguyengl99/chanx-kit/blob/main/sandbox/consumers.py';
const GROUPS = [...new Set(DEMOS.map((demo) => demo.group))];

/** The demo in the URL hash (`#/voice-agent`), so each one can be linked to. */
function useDemoId(): string {
  const read = () => window.location.hash.replace(/^#\/?/, '') || DEMOS[0].id;
  const [id, setId] = useState(read);
  useEffect(() => {
    const onChange = () => setId(read());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return id;
}

function useProviders(): Providers | null {
  const [providers, setProviders] = useState<Providers | null>(null);
  useEffect(() => {
    fetch('/api/providers')
      .then((response) => (response.ok ? response.json() : null))
      .then(setProviders)
      .catch(() => setProviders(null));
  }, []);
  return providers;
}

export function App() {
  const [who, setWho] = useState('chris');
  const id = useDemoId();
  const providers = useProviders() ?? { stt: 'fake-voice', tts: 'fake-voice' };
  const demo = DEMOS.find((candidate) => candidate.id === id) ?? DEMOS[0];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <h1>ChanX Kit</h1>
          <p className="hint">Sandbox</p>
        </div>
        <label>
          Connect as
          <input value={who} onChange={(event) => setWho(event.target.value)} />
        </label>
        <nav aria-label="Demos">
          {GROUPS.map((group) => (
            <div key={group} className="nav-group">
              <p className="nav-title">{group}</p>
              {DEMOS.filter((candidate) => candidate.group === group).map((candidate) => (
                <a
                  key={candidate.id}
                  href={`#/${candidate.id}`}
                  aria-current={candidate.id === demo.id ? 'page' : undefined}
                >
                  {candidate.title}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <p className="hint">
          Voice: <code>{providers.stt}</code> listens, <code>{providers.tts}</code> speaks.
          Set <code>DEEPGRAM_API_KEY</code> / <code>ELEVENLABS_API_KEY</code> in{' '}
          <code>.env</code> for real ones.
        </p>
        <p className="hint">
          <a href="/asyncapi">AsyncAPI docs</a> · <a href={`${DOCS}/`}>Kit docs</a>
        </p>
      </aside>

      <main>
        <header className="demo-head">
          <h2>{demo.title}</h2>
          <p>{demo.summary}</p>
          <dl className="demo-meta">
            <dt>Server kits</dt>
            <dd>
              {demo.kits(providers).map((kit) => (
                <a key={kit} className="chip" href={`${DOCS}/kits/${kit}/`}>
                  {kit}
                </a>
              ))}
            </dd>
            <dt>UI kits</dt>
            <dd>
              {demo.ui.map((kit) => (
                <a key={kit} className="chip" href={`${DOCS}/ui/${kit}/`}>
                  {kit}
                </a>
              ))}
            </dd>
            <dt>Consumer</dt>
            <dd>
              <a href={SOURCE}>
                <code>{demo.consumer}</code>
              </a>
            </dd>
          </dl>
        </header>
        {/* Keyed, so leaving a demo closes its socket and frees the microphone. */}
        <div key={demo.id} className="demo">
          {demo.render(who)}
        </div>
      </main>
    </div>
  );
}
