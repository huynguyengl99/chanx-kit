import { useRef } from 'react';

import { VoiceAgent, useVoiceAgent } from '../chanx-kit/voice-agent/react';
import { assistant } from '../generated';

/** voice-agent kit through the voice-agent UI kit. */
export function AssistantPanel() {
  const session = useRef(crypto.randomUUID().slice(0, 8));
  const agent = useVoiceAgent(assistant, {
    transcriber: assistant.topics.assistantEarsTopic.with({ session: session.current }),
    synthesizer: assistant.topics.assistantVoiceTopic.with({ session: session.current }),
    thread: assistant.topics.assistantTopic.with({ thread_id: session.current }),
  });

  return (
    <div className="stack">
      <VoiceAgent agent={agent} title="Voice agent" />
      <p className="hint">
        Talk, pause, and the agent answers out loud; speak over it to interrupt. With the
        fake transcriber every utterance is the same scripted sentence.
      </p>
    </div>
  );
}
