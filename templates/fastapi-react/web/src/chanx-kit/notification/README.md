# Notification feed

A live notification feed for any server speaking **notification@1**, such as the
`notification` server kit. Acknowledging sends one `notification_ack` per topic.

```bash
copit add @chanx-kit-ui/notification
```

## React

```tsx
import { NotificationFeed, useNotifications } from '@/chanx-kit/notification/react';
import '@/chanx-kit/notification/notification.css';
import { notifications } from '@/generated';

const everyone = notifications.topics.broadcastNotificationTopic.with();

export function Inbox({ userId }: { userId: string }) {
  const mine = notifications.topics.userNotificationTopic.with({ user_id: userId });
  const { items, status, ackAll, dismiss } = useNotifications(notifications, {
    topics: [mine, everyone],
  });
  return <NotificationFeed items={items} status={status} onAckAll={ackAll} onDismiss={dismiss} />;
}
```

The channel and topics come from your generated client, so the kit works whatever
you named them. Any topic whose messages fit the contract is accepted, including
subclasses that send more; one that does not fit is a type error.

## Without a framework

```ts
import { connectNotifications } from '@/chanx-kit/notification';

const inbox = connectNotifications(client, notifications, { topics: [everyone] });
inbox.feed.subscribe(() => render(inbox.feed.getSnapshot().items));
inbox.start();
```

`createNotificationFeed()` is the store alone: pass its `on` to any topics controller.

## Styling

`NotificationFeed` renders class names and `data-state` / `data-level` attributes
only. `notification.css` is the default look; skip it to style from scratch, or set
the `--chanx-*` variables (`--chanx-bg`, `--chanx-fg`, `--chanx-line`,
`--chanx-muted`, `--chanx-accent`, `--chanx-radius`, `--chanx-info`,
`--chanx-success`, `--chanx-warning`, `--chanx-error`) at `:root` to theme every kit.
