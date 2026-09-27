# Voice agent

Talk to an agent: an open microphone, live captions, the reply spoken as it streams,
and interrupting by speaking. For the [voice-agent server kit](../../kits/voice_agent),
or any server whose session speaks transcriber@1, synthesizer@1 and ag-ui@1 under one
id. Installing it brings the transcriber, player and ag-ui UI kits.

```bash
copit add @chanx-kit-ui/voice-agent
```

## React

```tsx
import { VoiceAgent, useVoiceAgent } from '@/chanx-kit/voice-agent/react';
import '@/chanx-kit/voice-agent/voice-agent.css';
import '@/chanx-kit/transcriber/transcriber.css';
import { voice } from '@/generated';

export function Assistant({ session }: { session: string }) {
  const agent = useVoiceAgent(voice, {
    transcriber: voice.topics.earsTopic.with({ session }),
    synthesizer: voice.topics.voiceTopic.with({ session }),
    thread: voice.topics.agentTopic.with({ thread_id: session }),
  });
  return <VoiceAgent agent={agent} />;
}
```

`useVoiceAgent` returns `status` (`idle`, `listening`, `thinking`, `speaking`), the live
`utterances`, the conversation `messages` (AG-UI messages), what is being `speaking`,
and `talk()` (from a click: it unlocks audio and opens the microphone), `mute()` and
`interrupt()`. Build your own UI on it, or use `<VoiceAgent>`.

## How a conversation flows

The microphone stays open across turns; the server decides where a turn ends (the
provider's `utterance_end`) and starts a run. The reply is spoken while it streams.
Speaking over it silences playback here at once, without waiting for the server,
which clears every listener, cancels the run and keeps only what was heard.

Use headphones or rely on the browser's echo cancellation (on by default): without it,
the agent can hear itself and interrupt its own reply.

## Without a framework

```ts
import { connectVoiceAgent } from '@/chanx-kit/voice-agent';

const agent = connectVoiceAgent(client, voice, { transcriber, synthesizer, thread });
agent.start();
talkButton.onclick = () => agent.talk();
```
