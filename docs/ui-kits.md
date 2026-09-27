# UI kits

A UI kit is the browser half of a kit: a framework-free store, React components on top,
and one CSS file. Like server kits, it is copied into your project and yours to edit.

A UI kit binds to a **contract** (the messages on a topic), not to one server kit. The
transcriber UI works with any server kit that speaks `transcriber@1`: Deepgram,
ElevenLabs, OpenAI or the fake one. Each kit page lists what it works with.

## Install

UI kits live in a second registry in the same repository. Add it once, next to the
server one, pointing at your web app's source folder:

```bash
uvx copit registry add chanx-kit-ui github:huynguyengl99/chanx-kit@v0.4.0 \
  --index ui/copit-registry.json --to web/src/chanx-kit
```

copit 0.9 sees React in `package.json` and selects the `react` variant; on older copit
add `--variant react`. Then install kits, usually alongside their server kit:

```bash
uvx copit add @chanx-kit/notification @chanx-kit-ui/notification
```

`@chanx-js/client` is installed for you. Kits import each other relatively, so they
work wherever `--to` puts them.

??? note "With shadcn instead"

    Every UI kit is also published as a shadcn registry item (React variant):

    ```bash
    npx shadcn add https://huynguyengl99.github.io/chanx-kit/r/notification.json
    ```

    Files land in `src/chanx-kit/<kit>/`.

## Use one

Generate the client from your server's AsyncAPI schema as usual, then pass the channel
and topics in. The kit never imports your generated code, so it works whatever you
named things:

```tsx
import { NotificationFeed, useNotifications } from '@/chanx-kit/notification/react';
import '@/chanx-kit/notification/notification.css';
import { notifications } from '@/generated';

export function Inbox({ userId }: { userId: string }) {
  const mine = notifications.topics.userNotificationTopic.with({ user_id: userId });
  const { items, status, ackAll } = useNotifications(notifications, { topics: [mine] });
  return <NotificationFeed items={items} status={status} onAckAll={ackAll} />;
}
```

A topic that does not speak the kit's contract is a type error. One that sends extra
messages of its own is fine.

## Without React

Each kit's `core.ts` has no framework in it: a store with `subscribe` / `getSnapshot`,
and a `connect*` function that joins the topic.

```ts
import { connectNotifications } from '@/chanx-kit/notification';

const inbox = connectNotifications(client, notifications, { topics: [mine] });
inbox.feed.subscribe(() => render(inbox.feed.getSnapshot().items));
inbox.start();
```

A Vue or Svelte binding is a small file over the same store.

## Styling

Components render class names and `data-*` attributes only; the look is one CSS file
per kit. Skip the import to style from scratch, or set variables once to theme every kit:

```css
:root {
  --chanx-bg: #fff;
  --chanx-fg: #1b1b1f;
  --chanx-line: #e3e3e8;
  --chanx-muted: #6b6b76;
  --chanx-accent: #2f6feb;
  --chanx-radius: 10px;
}
```

Unset, they fall back to system colours, so light and dark mode work unconfigured.

## Updating

`copit update-all` refreshes server and UI kits together, keeping your variant and any
parts you left out. Files you changed are kept unless you pass `--overwrite`.
