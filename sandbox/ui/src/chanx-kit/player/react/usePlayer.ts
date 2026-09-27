import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';
import type {
  AddressOf,
  ChannelDescriptor,
  ChanxMessage,
  HandlerMap,
  TopicControllerOptions,
  TopicRef,
  TopicRefOf,
} from '@chanx-js/client';
import { useTopic } from '@chanx-js/client/react';

import type { PlayerOptions, SendToSynthesizer, SynthesizerTopic } from '../core';
import { createPlayer } from '../core';

export type UsePlayerOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
> &
  Omit<PlayerOptions, 'speaker'>;

/** Play what a synthesizer topic speaks; ask it to speak or stop. */
export function usePlayer<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  channel: D,
  topic: Ref & SynthesizerTopic<Ref>,
  { prebufferMs, markEveryMs, workletUrl, ...options }: UsePlayerOptions<D> = {},
) {
  const player = useMemo(
    () => createPlayer({ prebufferMs, markEveryMs, workletUrl }),
    [prebufferMs, markEveryMs, workletUrl],
  );
  const { status, send: sendAny } = useTopic(channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: player.on as HandlerMap<ChanxMessage>,
  });
  const send: SendToSynthesizer = sendAny;
  useEffect(() => player.attach(send), [player, send]);
  useEffect(() => () => player.close(), [player]);

  const snapshot = useSyncExternalStore(player.subscribe, player.getSnapshot, player.getSnapshot);
  const speak = useCallback(
    (text: string, voice?: string) => send({ action: 'speak', payload: { text, voice: voice ?? null } }),
    [send],
  );
  const stop = useCallback(() => send({ action: 'speak_clear', payload: null }), [send]);
  const unlock = useCallback(() => player.unlock(), [player]);

  return { ...snapshot, connection: status, speak, stop, unlock, silence: player.silence };
}
