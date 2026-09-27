import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { SocketStatus } from '@chanx-js/client';

import { PresenceRoster } from '../../presence/react/PresenceRoster';
import type { PresenceMember } from '../../presence/contract';
import type { ChatEntry } from '../contract';

export interface ChatRoomProps {
  entries: ChatEntry[];
  onSend: (body: string) => void;
  status?: SocketStatus;
  /** Shown above the log when given, from `usePresence`. */
  members?: PresenceMember[];
  /** The viewer's own author id, so their messages can be told apart. */
  self?: string;
  title?: string;
  placeholder?: string;
}

/** Unstyled markup; import `chat.css` (and `presence.css` with `members`). */
export function ChatRoom({
  entries,
  onSend,
  status,
  members,
  self,
  title = 'Chat',
  placeholder = 'Say something…',
}: ChatRoomProps) {
  const [draft, setDraft] = useState('');
  const log = useRef<HTMLOListElement>(null);

  // Follow new messages, unless the reader scrolled up to read history.
  useEffect(() => {
    const element = log.current;
    if (!element) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
    if (nearBottom) element.scrollTop = element.scrollHeight;
  }, [entries]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim()) return;
    onSend(draft);
    setDraft('');
  };

  return (
    <section className="chanx-chat" data-state={status} aria-label={title}>
      <header className="chanx-chat__head">
        <h2>{title}</h2>
        {status && <span className="chanx-chat__status">{status}</span>}
      </header>

      {members && <PresenceRoster members={members} self={self} />}

      <ol className="chanx-chat__log" ref={log} aria-live="polite">
        {entries.map((entry, index) => (
          <li
            key={entry.id ?? index}
            className="chanx-chat__entry"
            data-self={entry.author.id === self || undefined}
          >
            <span className="chanx-chat__author">{entry.author.name ?? entry.author.id}</span>
            <span className="chanx-chat__body">{entry.body}</span>
          </li>
        ))}
      </ol>

      <form className="chanx-chat__composer" onSubmit={submit}>
        <input
          aria-label="Message"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={status !== undefined && status !== 'open'}>
          Send
        </button>
      </form>
    </section>
  );
}
