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

import type { RecorderOptions, TranscriberTopic, TranscriptOptions } from '../core';
import { createRecorder, createTranscript } from '../core';

export type UseTranscriberOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
> &
  Omit<RecorderOptions, 'microphone'> &
  TranscriptOptions;

/** Record from the microphone into a transcriber topic, and read its transcript. */
export function useTranscriber<
  D extends ChannelDescriptor<any, any, any, any>,
  Ref extends TopicRefOf<D>,
>(
  channel: D,
  topic: Ref & TranscriberTopic<Ref>,
  {
    config,
    language,
    constraints,
    workletUrl,
    limit,
    ...options
  }: UseTranscriberOptions<D> = {},
) {
  const transcript = useMemo(() => createTranscript({ limit }), [limit]);
  const recorder = useMemo(
    () => createRecorder({ config, language, constraints, workletUrl }),
    // The recorder holds the microphone; rebuild only when the capture setup changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [language, workletUrl],
  );

  const { status, send } = useTopic(channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: { ...transcript.on, ...recorder.on } as HandlerMap<ChanxMessage>,
  });

  const { utterances, speaking } = useSyncExternalStore(
    transcript.subscribe,
    transcript.getSnapshot,
    transcript.getSnapshot,
  );
  const recording = useSyncExternalStore(recorder.subscribe, recorder.getSnapshot, recorder.getSnapshot);

  // Release the microphone when the component goes away.
  useEffect(() => () => recorder.stop(send), [recorder, send]);

  const start = useCallback(() => recorder.start(send), [recorder, send]);
  const stop = useCallback(() => recorder.stop(send), [recorder, send]);

  return {
    utterances,
    speaking,
    recording: recording.status,
    level: recording.level,
    error: recording.error,
    status,
    start,
    stop,
    clear: transcript.clear,
  };
}
