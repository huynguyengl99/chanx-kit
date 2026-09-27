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

import { fromBase64, fromPcm16, Resampler } from '../audio/core';
import type { ContractToClient, ContractToServer, SynthesizerError } from './contract';
import type { Speaker, SpeakerFactory } from './speaker';
import { openSpeaker } from './speaker';

/** A topic whose messages fit synthesizer@1; extra actions are fine. */
export type SynthesizerTopic<Ref> =
  Ref extends TopicRef<infer ToServer, infer ToClient, any>
    ? [ContractToServer] extends [ToServer]
      ? [Extract<ToClient, { action: ContractToClient['action'] }>] extends [ContractToClient]
        ? Ref
        : never
      : never
    : never;

export type PlayerStatus = 'idle' | 'playing';

export interface PlayerSnapshot {
  status: PlayerStatus;
  /** The utterance being played, or last played. */
  utteranceId: string | null;
  text: string;
  /** How much of that utterance has been heard. */
  playedMs: number;
  durationMs: number | null;
  error: SynthesizerError | null;
  /** The browser is holding audio until a user gesture: call `unlock()` from one. */
  needsUnlock: boolean;
}

export interface PlayerOptions {
  prebufferMs?: number;
  /** Minimum time between playback marks for an utterance. */
  markEveryMs?: number;
  /** Defaults to the real audio output; tests pass a fake. */
  speaker?: SpeakerFactory;
  workletUrl?: string;
}

export type SendToSynthesizer = (message: ContractToServer) => void;

export interface Player {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => PlayerSnapshot;
  on: HandlerMap<ContractToClient>;
  /** Where playback marks go; set once the topic is joined. */
  attach: (send: SendToSynthesizer) => void;
  /** Open (or resume) audio output. Call from a click to satisfy autoplay rules. */
  unlock: () => Promise<void>;
  /** Stop playing now, locally, without waiting for the server's `clear`: barge-in. */
  silence: () => void;
  close: () => void;
}

interface Track {
  id: string;
  text: string;
  resampler: Resampler | null;
  channels: number;
  lastIndex: number;
  /** Where the utterance sits in the speaker's timeline, in speaker samples. */
  start: number;
  length: number;
  ended: boolean;
  durationMs: number | null;
  lastMarkMs: number;
  lastMarkAt: number;
}

export function createPlayer({
  prebufferMs = 150,
  markEveryMs = 250,
  speaker: openOutput = openSpeaker,
  workletUrl,
}: PlayerOptions = {}): Player {
  const listeners = new Set<() => void>();
  let snapshot: PlayerSnapshot = {
    status: 'idle',
    utteranceId: null,
    text: '',
    playedMs: 0,
    durationMs: null,
    error: null,
    needsUnlock: false,
  };
  let speaker: Speaker | null = null;
  let opening: Promise<Speaker> | null = null;
  let send: SendToSynthesizer | null = null;
  // The speaker's timeline, in its own samples.
  let written = 0;
  let played = 0;
  const tracks = new Map<string, Track>();
  // Audio that arrived while the speaker was opening, in order.
  let pending: Array<() => void> = [];

  const publish = (next: Partial<PlayerSnapshot>) => {
    snapshot = { ...snapshot, ...next };
    for (const listener of [...listeners]) listener();
  };

  const playedOf = (track: Track) => {
    if (!speaker) return 0;
    const heard = Math.min(Math.max(played - track.start, 0), track.length);
    return Math.round((heard / speaker.sampleRate) * 1000);
  };

  const mark = (track: Track, force = false) => {
    const playedMs = playedOf(track);
    const now = Date.now();
    if (!force && (playedMs === track.lastMarkMs || now - track.lastMarkAt < markEveryMs)) return;
    track.lastMarkMs = playedMs;
    track.lastMarkAt = now;
    send?.({ action: 'playback_mark', payload: { utterance_id: track.id, played_ms: playedMs } });
  };

  const onPlayed = (total: number) => {
    played = total;
    const current = snapshot.utteranceId ? tracks.get(snapshot.utteranceId) : undefined;
    for (const track of tracks.values()) {
      const done = track.ended && played >= track.start + track.length;
      mark(track, done);
      if (done) tracks.delete(track.id);
    }
    if (current) {
      const idle = tracks.size === 0;
      publish({ playedMs: playedOf(current), status: idle ? 'idle' : 'playing' });
    }
  };

  const ensureSpeaker = (): Promise<Speaker> => {
    if (speaker) return Promise.resolve(speaker);
    opening ??= openOutput({ prebufferMs, workletUrl }).then(
      (opened) => {
        speaker = opened;
        opened.onPlayed(onPlayed);
        publish({ needsUnlock: opened.suspended });
        for (const run of pending.splice(0)) run();
        return opened;
      },
      (error: unknown) => {
        // Let a later unlock() try again.
        opening = null;
        pending = [];
        const message = error instanceof Error ? error.message : String(error);
        publish({ error: { code: 'provider_failed', message: `Audio output unavailable: ${message}` } });
        throw error;
      },
    );
    return opening;
  };

  // Runs now if the speaker is open, or in arrival order once it is.
  const withSpeaker = (run: () => void) => {
    if (speaker) run();
    else {
      pending.push(run);
      ensureSpeaker().catch(() => {}); // reported through `error`
    }
  };

  const dropAll = () => {
    for (const track of tracks.values()) mark(track, true);
    tracks.clear();
    speaker?.clear();
    written = played;
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    attach(next) {
      send = next;
    },

    on: {
      audio_start: ({ payload }) =>
        withSpeaker(() => {
          if (tracks.has(payload.utterance_id)) return; // replayed
          tracks.set(payload.utterance_id, {
            id: payload.utterance_id,
            text: payload.text,
            resampler: new Resampler(payload.sample_rate ?? 24000, speaker!.sampleRate),
            channels: payload.channels ?? 1,
            lastIndex: -1,
            start: written,
            length: 0,
            ended: false,
            durationMs: null,
            lastMarkMs: -1,
            lastMarkAt: 0,
          });
          publish({
            status: 'playing',
            utteranceId: payload.utterance_id,
            text: payload.text,
            playedMs: 0,
            durationMs: null,
            error: null,
          });
        }),
      audio_chunk: ({ payload }) =>
        withSpeaker(() => {
          const track = tracks.get(payload.utterance_id);
          // Unknown (joined after its start was dropped) or already played: skip.
          if (!track || !track.resampler || payload.index <= track.lastIndex) return;
          track.lastIndex = payload.index;
          const samples = track.resampler.process(fromPcm16(fromBase64(payload.data), track.channels));
          track.length += samples.length;
          written += samples.length;
          speaker!.write(samples);
        }),
      audio_end: ({ payload }) =>
        withSpeaker(() => {
          const track = tracks.get(payload.utterance_id);
          if (!track) return;
          track.ended = true;
          track.durationMs = payload.duration_ms;
          if (snapshot.utteranceId === track.id) publish({ durationMs: payload.duration_ms });
          speaker!.drain();
          if (track.length === 0) {
            mark(track, true);
            tracks.delete(track.id);
            if (tracks.size === 0) publish({ status: 'idle' });
          }
        }),
      clear: () =>
        withSpeaker(() => {
          dropAll();
          publish({ status: 'idle' });
        }),
      synthesizer_error: ({ payload }) => publish({ error: payload }),
    },

    silence() {
      dropAll();
      publish({ status: 'idle' });
    },

    async unlock() {
      const opened = await ensureSpeaker();
      if (opened.suspended) await opened.resume();
      publish({ needsUnlock: opened.suspended });
    },

    close() {
      dropAll();
      speaker?.close();
      speaker = null;
      opening = null;
      pending = [];
    },
  };
}


export type ConnectPlayerOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
> &
  PlayerOptions;

/** Play a synthesizer topic, without a framework. Call `unlock()` from a click. */
export function connectPlayer<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  client: ChanxClient,
  channel: D,
  topic: Ref & SynthesizerTopic<Ref>,
  { prebufferMs, markEveryMs, speaker, workletUrl, ...options }: ConnectPlayerOptions<D> = {},
) {
  const player = createPlayer({ prebufferMs, markEveryMs, speaker, workletUrl });
  const controller = createTopicController(client, channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: player.on as HandlerMap<ChanxMessage>,
  });
  const send: SendToSynthesizer = (message) => controller.send(message);
  player.attach(send);
  return {
    player,
    controller,
    speak: (text: string, voice?: string) => send({ action: 'speak', payload: { text, voice: voice ?? null } }),
    /** Ask the server to stop speaking; every listener's player clears. */
    stop: () => send({ action: 'speak_clear', payload: null }),
    unlock: () => player.unlock(),
    start: () => controller.start(),
    close: () => {
      player.close();
      controller.stop();
    },
  };
}
