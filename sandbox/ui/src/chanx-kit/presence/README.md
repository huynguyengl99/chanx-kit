# Presence roster

Who is here, for any server speaking **presence@1**, such as the `presence` server
kit. The roster starts from `presence_state` and follows joins and leaves; a state
sent again (after a reconnect) replaces it.

```bash
copit add @chanx-kit-ui/presence
```

## React

```tsx
import { PresenceRoster, usePresence } from '@/chanx-kit/presence/react';
import '@/chanx-kit/presence/presence.css';
import { room } from '@/generated';

export function WhoIsHere({ name, me }: { name: string; me: string }) {
  const { members } = usePresence(room, room.topics.presenceTopic.with({ scope: name }), {
    params: { room: name },
  });
  return <PresenceRoster members={members} self={me} />;
}
```

`refresh()` asks for the roster again without reconnecting.

## Without a framework

```ts
import { connectPresence } from '@/chanx-kit/presence';

const lobby = connectPresence(client, room, room.topics.presenceTopic.with({ scope: 'lobby' }));
lobby.roster.subscribe(() => render(lobby.roster.getSnapshot().members));
lobby.start();
```

## Styling

`presence.css` is the default look, driven by the shared `--chanx-*` variables.
