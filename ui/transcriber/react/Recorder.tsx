import type { RecorderStatus } from '../core';

export interface RecorderProps {
  recording: RecorderStatus;
  level?: number;
  /** A transcriber error, or any `{ code, message }`. */
  error?: { code: string; message: string } | null;
  onStart: () => void;
  onStop: () => void;
  /** Disable while the socket is not open. */
  disabled?: boolean;
  startLabel?: string;
  stopLabel?: string;
}

/** A record toggle with an input level meter. Unstyled; import `transcriber.css`. */
export function Recorder({
  recording,
  level = 0,
  error,
  onStart,
  onStop,
  disabled,
  startLabel = 'Start recording',
  stopLabel = 'Stop recording',
}: RecorderProps) {
  const active = recording !== 'idle';
  return (
    <div className="chanx-recorder" data-state={recording}>
      <button
        type="button"
        className="chanx-recorder__toggle"
        aria-pressed={active}
        disabled={disabled && !active}
        onClick={active ? onStop : onStart}
      >
        <span className="chanx-recorder__dot" aria-hidden="true" />
        {active ? stopLabel : startLabel}
      </button>
      <span
        className="chanx-recorder__meter"
        role="meter"
        aria-label="Input level"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(level * 100)}
      >
        <span style={{ transform: `scaleX(${Math.min(1, level * 4)})` }} />
      </span>
      {error && (
        <p className="chanx-recorder__error" role="alert" data-code={error.code}>
          {error.message}
        </p>
      )}
    </div>
  );
}
