import type { ReactNode } from 'react';

import type { PresenceMember } from '../contract';

export interface PresenceRosterProps {
  members: PresenceMember[];
  /** The viewer's own member id, marked as "you". */
  self?: string;
  label?: string;
  empty?: ReactNode;
}

/** Unstyled markup; import `presence.css` for the default look. */
export function PresenceRoster({ members, self, label = 'Present', empty = 'Nobody here yet' }: PresenceRosterProps) {
  return (
    <ul className="chanx-presence" aria-label={label} aria-live="polite">
      {members.length === 0 && <li className="chanx-presence__empty">{empty}</li>}
      {members.map((member) => {
        const name = member.name ?? member.id;
        return (
          <li key={member.id} className="chanx-presence__member" data-self={member.id === self || undefined}>
            <span className="chanx-presence__avatar" aria-hidden="true">
              {name.slice(0, 1).toUpperCase()}
            </span>
            {name}
            {member.id === self && <span className="chanx-presence__you"> (you)</span>}
          </li>
        );
      })}
    </ul>
  );
}
