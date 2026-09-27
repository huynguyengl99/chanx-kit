import { Recorder } from '../../transcriber/react/Recorder';
import { TranscriptView } from '../../transcriber/react/TranscriptView';
import type { useVoiceAgent } from './useVoiceAgent';

export interface VoiceAgentProps {
  agent: ReturnType<typeof useVoiceAgent>;
  title?: string;
}

const STATUS_LABEL = {
  idle: 'Tap to talk',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
} as const;

/** Talk button, live captions and the reply. Unstyled; see the README for CSS. */
export function VoiceAgent({ agent, title = 'Voice agent' }: VoiceAgentProps) {
  const lastReply = [...agent.messages].reverse().find((message) => message.role === 'assistant');
  return (
    <section className="chanx-voice-agent" data-status={agent.status} aria-label={title}>
      <header className="chanx-voice-agent__head">
        <h2>{title}</h2>
        <span className="chanx-voice-agent__status" role="status">
          {STATUS_LABEL[agent.status]}
        </span>
      </header>

      <Recorder
        recording={agent.recording}
        level={agent.level}
        error={agent.error}
        onStart={() => void agent.talk()}
        onStop={agent.mute}
        disabled={agent.connection !== 'open'}
        startLabel="Start talking"
        stopLabel="Mute"
      />

      <TranscriptView utterances={agent.utterances.slice(-3)} label="You said" empty="Say something." />

      <div className="chanx-voice-agent__reply" aria-live="polite">
        {agent.speaking || (lastReply && typeof lastReply.content === 'string' ? lastReply.content : '')}
      </div>

      {(agent.status === 'speaking' || agent.status === 'thinking') && (
        <button type="button" className="chanx-voice-agent__interrupt" onClick={agent.interrupt}>
          Stop the reply
        </button>
      )}
    </section>
  );
}
