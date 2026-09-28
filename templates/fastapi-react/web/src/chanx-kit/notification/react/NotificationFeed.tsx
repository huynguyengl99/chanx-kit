import type { ReactNode } from 'react';
import type { SocketStatus } from '@chanx-js/client';

import type { ReceivedNotification } from '../core';

export interface NotificationFeedProps {
  items: ReceivedNotification[];
  status?: SocketStatus;
  onAckAll?: () => void;
  onDismiss?: (id: string) => void;
  /** Label for the topic an item came on. */
  describeTopic?: (topic: string) => string | undefined;
  title?: string;
  empty?: ReactNode;
}

/** Unstyled markup; import `notification.css` for the default look. */
export function NotificationFeed({
  items,
  status,
  onAckAll,
  onDismiss,
  describeTopic,
  title = 'Notifications',
  empty = 'No notifications yet.',
}: NotificationFeedProps) {
  return (
    <section className="chanx-notifications" data-state={status} aria-label={title}>
      <header className="chanx-notifications__head">
        <h2>{title}</h2>
        {status && <span className="chanx-notifications__status">{status}</span>}
      </header>

      <ul className="chanx-notifications__list" aria-live="polite">
        {items.length === 0 && <li className="chanx-notifications__empty">{empty}</li>}
        {items.map((item) => {
          const where = describeTopic?.(item.topic);
          return (
            <li key={item.id} className="chanx-notifications__item" data-level={item.level ?? 'info'}>
              <strong>{item.title}</strong>
              {item.body && <span>{item.body}</span>}
              {where && <small className="chanx-notifications__topic">{where}</small>}
              {onDismiss && (
                <button
                  type="button"
                  className="chanx-notifications__dismiss"
                  aria-label={`Dismiss ${item.title}`}
                  onClick={() => onDismiss(item.id)}
                >
                  ×
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {onAckAll && (
        <button
          type="button"
          className="chanx-notifications__ack"
          onClick={onAckAll}
          disabled={items.length === 0}
        >
          Acknowledge all
        </button>
      )}
    </section>
  );
}
