import { useRef, useState } from 'react';

import { Player, usePlayer } from '../chanx-kit/player/react';
import { voice } from '../generated';

/** audio-stream-out through the player UI kit; ElevenLabs if keyed, else the fake. */
export function SpeechPanel() {
  const session = useRef(crypto.randomUUID().slice(0, 8));
  const [text, setText] = useState('Hello from the speech kit. Every tab on this session hears me.');
  const player = usePlayer(voice, voice.topics.demoSynthesizerTopic.with({ session: session.current }));

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Voice · text to speech</h2>
        <span className="status" data-state={player.connection}>
          {player.connection}
        </span>
      </div>
      <Player {...player} onUnlock={player.unlock} onStop={player.stop} />
      <div className="row">
        <textarea rows={2} value={text} onChange={(event) => setText(event.target.value)} />
      </div>
      <div className="row">
        <button
          onClick={() => {
            // The click that speaks also unlocks audio, so autoplay rules are met.
            void player.unlock();
            player.speak(text);
          }}
          disabled={player.connection !== 'open'}
        >
          Speak
        </button>
      </div>
      <p className="hint">
        Session <code>{session.current}</code>. Queue several and they play in order; Stop
        clears every listener. Without <code>ELEVENLABS_API_KEY</code> each word is a tone.
      </p>
    </section>
  );
}
