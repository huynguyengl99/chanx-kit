import type {
  AddressOf,
  ChanxClient,
  ChannelDescriptor,
  ChanxMessage,
  HandlerMap,
  TopicControllerOptions,
  TopicRef,
  TopicRefOf,
} from '@chanx-js/client';
import { createTopicController } from '@chanx-js/client';

import { toBase64 } from '../audio/core';
import type {
  AudioConfig,
  ContractToClient,
  ContractToServer,
  TranscriberError,
} from './contract';
import type { Microphone, MicrophoneFactory, MicrophoneOptions } from './microphone';
import { openMicrophone } from './microphone';

type Fits<Ref, Server, Client extends { action: string }> =
  Ref extends TopicRef<infer ToServer, infer ToClient, any>
    ? [Server] extends [ToServer]
      ? [Extract<ToClient, { action: Client['action'] }>] extends [Client]
        ? Ref
        : never
      : never
    : never;

/** A topic that speaks transcriber@1: `transcribe:{session}`. */
export type TranscriberTopic<Ref> = Fits<Ref, ContractToServer, ContractToClient>;

type TranscriptMessage = Extract<
  ContractToClient,
  { action: 'speech_started' | 'transcript_partial' | 'transcript_final' | 'utterance_end' }
>;

/** A topic that only watches transcripts: `transcript:{session}`. */
export type TranscriptWatchTopic<Ref> = Fits<Ref, never, TranscriptMessage>;


export interface Utterance {
  id: string;
  /** Finalized segments, in order. */
  finals: string[];
  /** The segment being spoken, until it is finalized. */
  partial: string;
  /** The speaker paused: nothing more will be added. */
  done: boolean;
  startMs: number;
  endMs: number;
}

/** An utterance's text so far: its finals, then the partial. */
export const utteranceText = (utterance: Utterance): string =>
  [...utterance.finals, utterance.partial].filter(Boolean).join(' ');

export interface TranscriptSnapshot {
  utterances: Utterance[];
  /** True between `speech_started` and the next `utterance_end`. */
  speaking: boolean;
}

export interface Transcript {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => TranscriptSnapshot;
  on: HandlerMap<TranscriptMessage>;
  clear: () => void;
}

export interface TranscriptOptions {
  /** Max utterances kept, oldest dropped. Defaults to 100. */
  limit?: number;
}

export function createTranscript({ limit = 100 }: TranscriptOptions = {}): Transcript {
  const listeners = new Set<() => void>();
  let snapshot: TranscriptSnapshot = { utterances: [], speaking: false };

  const publish = (next: Partial<TranscriptSnapshot>) => {
    snapshot = { ...snapshot, ...next };
    for (const listener of [...listeners]) listener();
  };

  const update = (id: string, change: (utterance: Utterance) => Utterance, startMs = 0) => {
    const utterances = [...snapshot.utterances];
    const index = utterances.findIndex((utterance) => utterance.id === id);
    if (index === -1) {
      utterances.push(
        change({ id, finals: [], partial: '', done: false, startMs, endMs: startMs }),
      );
    } else {
      utterances[index] = change(utterances[index]!);
    }
    publish({ utterances: utterances.slice(-limit) });
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    on: {
      speech_started: () => publish({ speaking: true }),
      transcript_partial: ({ payload }) =>
        update(
          payload.utterance_id,
          (utterance) => ({ ...utterance, partial: payload.text, endMs: payload.end_ms }),
          payload.start_ms,
        ),
      transcript_final: ({ payload }) =>
        update(
          payload.utterance_id,
          (utterance) =>
            // A final replayed after a reconnect must not be added twice.
            utterance.finals.at(-1) === payload.text && utterance.endMs >= payload.end_ms
              ? utterance
              : {
                  ...utterance,
                  finals: [...utterance.finals, payload.text],
                  partial: '',
                  endMs: payload.end_ms,
                },
          payload.start_ms,
        ),
      utterance_end: ({ payload }) => {
        publish({ speaking: false });
        if (snapshot.utterances.some((utterance) => utterance.id === payload.utterance_id)) {
          update(payload.utterance_id, (utterance) => ({ ...utterance, partial: '', done: true }));
        }
      },
    },
    clear: () => publish({ utterances: [], speaking: false }),
  };
}


export type RecorderStatus = 'idle' | 'starting' | 'recording';

export interface RecorderSnapshot {
  status: RecorderStatus;
  /** Input level, 0 to 1. */
  level: number;
  /** The last error from the server or the microphone; cleared on start. */
  error: TranscriberError | null;
  /** The format the server asked for, once `audio_config` arrived. */
  config: AudioConfig | null;
}

export interface RecorderOptions {
  /** Used until the server's `audio_config` arrives. */
  config?: AudioConfig;
  language?: string;
  /** Defaults to the real microphone; tests pass a fake. */
  microphone?: MicrophoneFactory;
  constraints?: MicrophoneOptions['constraints'];
  workletUrl?: string;
}

export type SendToTranscriber = (message: ContractToServer) => void;

export interface Recorder {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => RecorderSnapshot;
  on: HandlerMap<Extract<ContractToClient, { action: 'audio_config' | 'transcriber_error' }>>;
  start: (send: SendToTranscriber) => Promise<void>;
  stop: (send: SendToTranscriber) => void;
}

const DEFAULT_CONFIG: AudioConfig = {
  encoding: 'pcm16',
  sample_rate: 24000,
  channels: 1,
  chunk_ms: 100,
};

export function createRecorder(options: RecorderOptions = {}): Recorder {
  const listeners = new Set<() => void>();
  const open = options.microphone ?? openMicrophone;
  let snapshot: RecorderSnapshot = {
    status: 'idle',
    level: 0,
    error: null,
    config: null,
  };
  let microphone: Microphone | null = null;
  let sendCurrent: SendToTranscriber | null = null;
  // Lets a start still waiting for the microphone see it was cancelled.
  let generation = 0;

  const publish = (next: Partial<RecorderSnapshot>) => {
    snapshot = { ...snapshot, ...next };
    for (const listener of [...listeners]) listener();
  };

  const release = () => {
    microphone?.stop();
    microphone = null;
  };

  const recorder: Recorder = {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    on: {
      audio_config: ({ payload }) => publish({ config: payload }),
      transcriber_error: ({ payload }) => {
        publish({ error: payload });
        // A gap loses a little audio; everything else ends the stream server-side.
        if (payload.code !== 'audio_gap' && snapshot.status !== 'idle') {
          generation++;
          release();
          sendCurrent = null;
          publish({ status: 'idle', level: 0 });
        }
      },
    },

    async start(send) {
      if (snapshot.status !== 'idle') return;
      const current = ++generation;
      const config = { ...DEFAULT_CONFIG, ...options.config, ...snapshot.config };
      const sampleRate = config.sample_rate ?? 24000;
      publish({ status: 'starting', error: null });

      let index = 0;
      let started = false;
      const held: Uint8Array[] = [];
      const sendChunk = (chunk: Uint8Array) =>
        send({ action: 'audio_chunk', payload: { index: index++, data: toBase64(chunk) } });
      // Audio captured before audio_start is sent waits for it.
      const onChunk = (chunk: Uint8Array) => (started ? sendChunk(chunk) : held.push(chunk));

      try {
        const opened = await open({
          sampleRate,
          chunkMs: config.chunk_ms ?? 100,
          onChunk,
          onLevel: (value) => publish({ level: value }),
          constraints: options.constraints,
          workletUrl: options.workletUrl,
        });
        if (current !== generation) {
          opened.stop();
          return;
        }
        microphone = opened;
      } catch (error) {
        if (current === generation) {
          publish({
            status: 'idle',
            error: {
              code: 'provider_unavailable',
              message: `Microphone unavailable: ${error instanceof Error ? error.message : String(error)}`,
            },
          });
        }
        return;
      }

      send({
        action: 'audio_start',
        payload: {
          encoding: 'pcm16',
          sample_rate: sampleRate,
          channels: config.channels ?? 1,
          ...(options.language ? { language: options.language } : {}),
        },
      });
      started = true;
      held.splice(0).forEach(sendChunk);
      sendCurrent = send;
      publish({ status: 'recording' });
    },

    stop(send) {
      if (snapshot.status === 'idle') return;
      const wasRecording = snapshot.status === 'recording';
      generation++;
      // Flushes the last partial chunk through onChunk before audio_end.
      release();
      if (wasRecording) (sendCurrent ?? send)({ action: 'audio_end', payload: null });
      sendCurrent = null;
      publish({ status: 'idle', level: 0 });
    },
  };
  return recorder;
}


export type ConnectTranscriberOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
> &
  RecorderOptions &
  TranscriptOptions;

/** Record into a transcriber topic and collect its transcript, without a framework. */
export function connectTranscriber<
  D extends ChannelDescriptor<any, any, any, any>,
  Ref extends TopicRefOf<D>,
>(
  client: ChanxClient,
  channel: D,
  topic: Ref & TranscriberTopic<Ref>,
  {
    config,
    language,
    microphone,
    constraints,
    workletUrl,
    limit,
    ...options
  }: ConnectTranscriberOptions<D> = {},
) {
  const transcript = createTranscript({ limit });
  const recorder = createRecorder({ config, language, microphone, constraints, workletUrl });
  const controller = createTopicController(client, channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: { ...transcript.on, ...recorder.on } as HandlerMap<ChanxMessage>,
  });
  const send: SendToTranscriber = (message) => controller.send(message);
  return {
    transcript,
    recorder,
    controller,
    record: () => recorder.start(send),
    stop: () => recorder.stop(send),
    start: () => controller.start(),
    close: () => {
      recorder.stop(send);
      controller.stop();
    },
  };
}
