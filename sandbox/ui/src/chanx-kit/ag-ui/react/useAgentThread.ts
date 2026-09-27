import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
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

import type { RunAgentInput } from '../contract';
import type { AgUiEvent, AgUiThreadTopic } from '../core';
import { createAgentThread } from '../core';

export type UseAgentThreadOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
> & {
  /** Defaults to the topic's `thread_id` param. */
  threadId?: string;
  /** Every event, after it is applied: for `STATE_DELTA`, `CUSTOM` and the like. */
  onEvent?: (event: AgUiEvent) => void;
};

/** One AG-UI conversation: its messages, the run in flight, and `run` / `cancel`. */
export function useAgentThread<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  channel: D,
  topic: Ref & AgUiThreadTopic<Ref>,
  { threadId, onEvent, ...options }: UseAgentThreadOptions<D> = {},
) {
  const id = threadId ?? String((topic as TopicRef).params.thread_id ?? '');
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  });
  const thread = useMemo(
    () => createAgentThread({ threadId: id, onEvent: (event) => onEventRef.current?.(event) }),
    [id],
  );

  const { status, send } = useTopic(channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: thread.on as HandlerMap<ChanxMessage>,
  });

  const snapshot = useSyncExternalStore(thread.subscribe, thread.getSnapshot, thread.getSnapshot);
  const run = useCallback(
    (text: string, input?: Partial<RunAgentInput>) => thread.run(send, text, input),
    [thread, send],
  );
  const cancel = useCallback(() => thread.cancel(send), [thread, send]);

  return { ...snapshot, status, run, cancel };
}
