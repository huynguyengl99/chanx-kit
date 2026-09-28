import type { ReactNode } from 'react';

import { AgentPanel } from './panels/AgentPanel';
import { AssistantPanel } from './panels/AssistantPanel';
import { NotificationPanel } from './panels/NotificationPanel';
import { RoomPanel } from './panels/RoomPanel';
import { SpeechPanel } from './panels/SpeechPanel';
import { VoicePanel } from './panels/VoicePanel';

export interface Providers {
  stt: string;
  tts: string;
}

export interface Demo {
  id: string;
  title: string;
  group: 'Messaging' | 'Agents' | 'Voice';
  summary: string;
  /** Server kits, given which providers the server picked. */
  kits: (providers: Providers) => string[];
  ui: string[];
  consumer: string;
  render: (who: string) => ReactNode;
}

/** One page per demo, grouped as in the docs. */
export const DEMOS: [Demo, ...Demo[]] = [
  {
    id: 'notifications',
    title: 'Notifications',
    group: 'Messaging',
    summary: "Push to a user's open tabs from a signal, a worker or another service.",
    kits: () => ['notification'],
    ui: ['notification'],
    consumer: 'NotificationConsumer',
    render: (who) => <NotificationPanel who={who} />,
  },
  {
    id: 'room',
    title: 'Chat room',
    group: 'Messaging',
    summary: 'History replayed on join and a live roster, two kits over one socket.',
    kits: () => ['room-chat', 'presence'],
    ui: ['chat', 'presence'],
    consumer: 'RoomConsumer',
    render: (who) => <RoomPanel who={who} />,
  },
  {
    id: 'agent',
    title: 'AG-UI',
    group: 'Agents',
    summary: 'The AG-UI protocol over a chanx websocket, streamed event by event.',
    kits: () => ['ag-ui'],
    ui: ['ag-ui'],
    consumer: 'AgentConsumer',
    render: () => <AgentPanel />,
  },
  {
    id: 'speech-to-text',
    title: 'Speech to text',
    group: 'Voice',
    summary: 'Microphone audio in, live captions out, for any transcriber provider.',
    kits: ({ stt }) => ['audio-stream-in', stt],
    ui: ['transcriber'],
    consumer: 'VoiceConsumer',
    render: () => <VoicePanel />,
  },
  {
    id: 'text-to-speech',
    title: 'Text to speech',
    group: 'Voice',
    summary: 'Text in, speech out to every listener on the session.',
    kits: ({ tts }) => ['audio-stream-out', tts],
    ui: ['player'],
    consumer: 'VoiceConsumer',
    render: () => <SpeechPanel />,
  },
  {
    id: 'voice-agent',
    title: 'Voice agent',
    group: 'Voice',
    summary: 'Talk to an AG-UI agent, hear it answer, interrupt it by speaking.',
    kits: ({ stt, tts }) => [...new Set(['voice-agent', stt, tts])],
    ui: ['voice-agent'],
    consumer: 'AssistantConsumer',
    render: () => <AssistantPanel />,
  },
];
