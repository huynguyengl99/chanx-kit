import type { PlayerStatus } from '../core';
import type { SynthesizerError } from '../contract';

export interface PlayerProps {
  status: PlayerStatus;
  text?: string;
  playedMs?: number;
  durationMs?: number | null;
  error?: SynthesizerError | null;
  needsUnlock?: boolean;
  onUnlock?: () => void;
  onStop?: () => void;
  label?: string;
}

/** What is being said, how far along, and a stop button. Unstyled; import `player.css`. */
export function Player({
  status,
  text,
  playedMs = 0,
  durationMs,
  error,
  needsUnlock,
  onUnlock,
  onStop,
  label = 'Speech',
}: PlayerProps) {
  const progress = durationMs ? Math.min(1, playedMs / durationMs) : 0;
  return (
    <section className="chanx-player" data-state={status} aria-label={label}>
      {needsUnlock && onUnlock && (
        <button type="button" className="chanx-player__unlock" onClick={onUnlock}>
          Enable audio
        </button>
      )}
      <p className="chanx-player__text" aria-live="polite">
        {text || (status === 'idle' ? 'Nothing playing.' : '')}
      </p>
      <span
        className="chanx-player__progress"
        role="progressbar"
        aria-label="Played"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <span style={{ transform: `scaleX(${progress})` }} />
      </span>
      {onStop && (
        <button type="button" className="chanx-player__stop" onClick={onStop} disabled={status === 'idle'}>
          Stop
        </button>
      )}
      {error && (
        <p className="chanx-player__error" role="alert" data-code={error.code}>
          {error.message}
        </p>
      )}
    </section>
  );
}
