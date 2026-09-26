import { useState } from 'react';
import { useTopics } from '@chanx-js/client/react';

import { room } from '../generated';
import type { ChatEntry, PresenceMember } from '../generated';

const ROOM = 'general';
const chat = room.topics.demoChatTopic.with({ room: ROOM });
const presence = room.topics.demoPresenceTopic.with({ scope: ROOM });

/** Two independent kits — chat and presence — over a single connection. */
export function RoomPanel({ who }: { who: string }) {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [members, setMembers] = useState<PresenceMember[]>([]);
  const [draft, setDraft] = useState('');

  const { sendTopic, status } = useTopics(room, {
    params: { room: ROOM },
    queryParams: { as: who },
    topics: [chat, presence],
    buffer: 'none',
    // Keyed by action and typed from the joined topics, so each payload needs no cast.
    on: {
      chat_backlog: (message) => setEntries(message.payload.entries),
      chat_message: (message) => setEntries((current) => [...current, message.payload]),
      presence_state: (message) => setMembers(message.payload.members),
      presence_join: ({ payload }) =>
        setMembers((current) =>
          current.some((member) => member.id === payload.member.id)
            ? current
            : [...current, payload.member],
        ),
      presence_leave: ({ payload }) =>
        setMembers((current) => current.filter((member) => member.id !== payload.member.id)),
    },
  });

  const post = () => {
    if (!draft.trim()) return;
    sendTopic(chat.topic, { action: 'chat_send', payload: { body: draft } });
    setDraft('');
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Room · chat-history + presence</h2>
        <span className="status" data-state={status}>
          {status}
        </span>
      </div>

      <div className="roster">
        {members.length === 0 && <span className="chip">nobody here yet</span>}
        {members.map((member) => (
          <span className="chip" key={member.id}>
            {member.name ?? member.id}
          </span>
        ))}
      </div>

      <ul className="log">
        {entries.map((entry) => (
          <li key={entry.id}>
            <span className="who">{entry.author.name ?? entry.author.id}</span>{' '}
            {entry.body}
          </li>
        ))}
      </ul>

      <div className="row">
        <input
          value={draft}
          placeholder="Say something…"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && post()}
        />
        <button onClick={post} disabled={status !== 'open'}>
          Send
        </button>
      </div>
      <p className="hint">
        Open a second tab with a different name — history replays on connect and the
        roster updates live.
      </p>
    </section>
  );
}
