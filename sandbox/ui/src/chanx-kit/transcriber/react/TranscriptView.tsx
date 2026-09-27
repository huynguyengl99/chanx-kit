import type { ReactNode } from 'react';

import type { Utterance } from '../core';

export interface TranscriptViewProps {
  utterances: Utterance[];
  /** Show a listening indicator while speech is in progress. */
  speaking?: boolean;
  label?: string;
  empty?: ReactNode;
}

/** Live captions: finals as settled text, the partial as it changes. Unstyled. */
export function TranscriptView({
  utterances,
  speaking,
  label = 'Transcript',
  empty = 'Nothing transcribed yet.',
}: TranscriptViewProps) {
  return (
    <section className="chanx-transcript" aria-label={label} data-speaking={speaking || undefined}>
      {/* Only settled text is announced; partials change too often to read out. */}
      <ol className="chanx-transcript__list" aria-live="polite" aria-relevant="additions text">
        {utterances.length === 0 && <li className="chanx-transcript__empty">{empty}</li>}
        {utterances.map((utterance) => (
          <li key={utterance.id} className="chanx-transcript__utterance" data-done={utterance.done || undefined}>
            {utterance.finals.join(' ')}
            {utterance.partial && (
              <span className="chanx-transcript__partial" aria-hidden="true">
                {utterance.finals.length > 0 ? ' ' : ''}
                {utterance.partial}
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
