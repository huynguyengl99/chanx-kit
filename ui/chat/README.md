# Chat room

A chat log and composer for any server speaking **chat@1**, such as the `room-chat`
server kit. History arrives on join; live messages append, each shown once. Installing
it also installs the presence UI kit, whose roster `ChatRoom` can show.

```bash
copit add @chanx-kit-ui/chat
```

## React

```tsx
import { ChatRoom, useChat } from '@/chanx-kit/chat/react';
import { usePresence } from '@/chanx-kit/presence/react';
import '@/chanx-kit/chat/chat.css';
import '@/chanx-kit/presence/presence.css';
import { room } from '@/generated';

export function Room({ name, me }: { name: string; me: string }) {
  const options = { params: { room: name } };
  // Same channel and options, so both hooks share one socket.
  const { entries, status, send } = useChat(room, room.topics.chatTopic.with({ room: name }), options);
  const { members } = usePresence(room, room.topics.presenceTopic.with({ scope: name }), options);
  return <ChatRoom entries={entries} status={status} onSend={send} members={members} self={me} />;
}
```

A message shows once the server publishes it back, so what is on screen is what was
saved. `requestBacklog(limit)` asks for history again.

## Without a framework

```ts
import { connectChat } from '@/chanx-kit/chat';

const lobby = connectChat(client, room, room.topics.chatTopic.with({ room: 'lobby' }));
lobby.log.subscribe(() => render(lobby.log.getSnapshot().entries));
lobby.start();
lobby.send('hello');
```

## Styling

`chat.css` is the default look, driven by the shared `--chanx-*` variables.
