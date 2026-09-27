import type { WebSocketLike } from '@chanx-js/client';
import { createClient, terminateAllSockets } from '@chanx-js/client';

export class FakeSocket implements WebSocketLike {
  static instances: FakeSocket[] = [];

  readyState = 0;
  sent: Array<Record<string, any>> = [];
  onopen: ((event: unknown) => void) | null = null;
  onclose: ((event: { code?: number; reason?: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  static get last(): FakeSocket {
    const socket = FakeSocket.instances.at(-1);
    if (!socket) throw new Error('No socket was created');
    return socket;
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.({});
  }

  accept(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  receive(frame: object): void {
    this.onmessage?.({ data: JSON.stringify({ version: 1, ...frame }) });
  }

  /** Frames sent on a topic, subscription requests excluded. */
  sentOn(topic: string): Array<Record<string, any>> {
    return this.sent.filter((frame) => frame.topic === topic && frame.action !== 'subscribe');
  }
}

export function makeClient() {
  return createClient({
    baseUrl: 'ws://test.local',
    socketFactory: (url) => new FakeSocket(url),
    closeDelay: 0,
    heartbeat: false,
  });
}

export function reset(): void {
  terminateAllSockets();
  FakeSocket.instances = [];
}

/** Open the socket and confirm every subscription it asked for. */
export function open(): FakeSocket {
  const socket = FakeSocket.last;
  socket.accept();
  for (const frame of socket.sent.filter((f) => f.action === 'subscribe')) {
    socket.receive({ topic: frame.topic, ref: frame.ref, action: 'subscribed', payload: null });
  }
  return socket;
}
