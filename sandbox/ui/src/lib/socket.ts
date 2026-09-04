import { useCallback, useEffect, useRef, useState } from 'react';

export type Status = 'connecting' | 'open' | 'closed';

/** Routing metadata chanx carries alongside a message on the same flat frame. */
interface Envelope {
  version: number;
  topic?: string;
  ref?: string;
  seq?: number;
}

const ENVELOPE_VERSION = 1;

/**
 * One socket serving several topics.
 *
 * Each topic is subscribed on open and addressed per frame, so a panel needing two
 * streams — chat and its roster — opens one connection rather than two. Frames are
 * delivered with the topic they arrived on and the envelope stripped, so the handler
 * sees the same message shapes the schema declares.
 */
export function useTopics<
  ToClient extends { action: string },
  ToServer extends { action: string },
>(
  path: string,
  topics: string[],
  onMessage: (message: ToClient, topic: string) => void,
): { send: (topic: string, message: ToServer) => void; status: Status } {
  const [status, setStatus] = useState<Status>('connecting');
  const socketRef = useRef<WebSocket | null>(null);
  const refRef = useRef(0);

  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  // Resubscribing must not depend on array identity, which changes every render.
  const topicKey = topics.join(' ');

  useEffect(() => {
    const wanted = topicKey.split(' ').filter(Boolean);
    const url = new URL(path, window.location.href);
    url.protocol = url.protocol.replace('http', 'ws');

    const socket = new WebSocket(url);
    socketRef.current = socket;
    setStatus('connecting');

    socket.onopen = () => {
      setStatus('open');
      for (const topic of wanted) {
        refRef.current += 1;
        socket.send(
          JSON.stringify({
            version: ENVELOPE_VERSION,
            topic,
            ref: String(refRef.current),
            action: 'subscribe',
          }),
        );
      }
    };
    socket.onclose = () => setStatus('closed');
    socket.onmessage = (event) => {
      const frame = JSON.parse(event.data) as Envelope & { action: string };
      if (!frame.topic || !wanted.includes(frame.topic)) return;
      // subscribe/unsubscribe confirmations are protocol frames, not a topic's own
      if (frame.action === 'subscribed' || frame.action === 'unsubscribed') return;

      const { version, topic, ref, seq, ...message } = frame;
      void version;
      void ref;
      void seq;
      handlerRef.current(message as unknown as ToClient, topic);
    };

    return () => socket.close();
  }, [path, topicKey]);

  const send = useCallback((topic: string, message: ToServer) => {
    const socket = socketRef.current;
    if (socket?.readyState !== WebSocket.OPEN) return;
    refRef.current += 1;
    socket.send(
      JSON.stringify({
        version: ENVELOPE_VERSION,
        topic,
        ref: String(refRef.current),
        ...message,
      }),
    );
  }, []);

  return { send, status };
}
