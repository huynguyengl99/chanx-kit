import { useRef } from 'react';

import { Recorder, TranscriptView, useTranscriber, useTranscript } from '../chanx-kit/transcriber/react';
import { voice } from '../generated';

/** audio-stream-in through the transcriber UI kit; Deepgram if keyed, else the fake. */
export function VoicePanel() {
  const session = useRef(crypto.randomUUID().slice(0, 8));
  const { utterances, speaking, recording, level, error, status, start, stop } = useTranscriber(
    voice,
    voice.topics.demoTranscriberTopic.with({ session: session.current }),
  );
  // The same session, watched read-only, as another tab would.
  const watched = useTranscript(voice, voice.topics.transcriptTopic.with({ session: session.current }));

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Voice · speech to text</h2>
        <span className="status" data-state={status}>
          {status}
        </span>
      </div>
      <Recorder
        recording={recording}
        level={level}
        error={error}
        onStart={start}
        onStop={stop}
        disabled={status !== 'open'}
      />
      <TranscriptView utterances={utterances} speaking={speaking} />
      <p className="hint">
        Session <code>{session.current}</code>. A watcher on <code>transcript:{session.current}</code>{' '}
        has {watched.utterances.length} utterance{watched.utterances.length === 1 ? '' : 's'}.
        Without <code>DEEPGRAM_API_KEY</code> the server transcribes a scripted sentence.
      </p>
    </section>
  );
}
