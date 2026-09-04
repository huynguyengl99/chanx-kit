import { useState } from 'react';

import type {
  ChatEntry,
  PresenceMember,
  RoomDemoChatTopicToClient,
  RoomDemoChatTopicToServer,
  RoomDemoPresenceTopicToClient,
} from '../generated';
import { useTopics } from '../lib/socket';

const ROOM = 'general';
const CHAT = `chat:${ROOM}`;
const PRESENCE = `presence:${ROOM}`;

/** Two independent kits — chat and presence — over a single connection. */
export function RoomPanel({ who }: { who: string }) {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [members, setMembers] = useState<PresenceMember[]>([]);
  const [draft, setDraft] = useState('');

  const { send, status } = useTopics<
    RoomDemoChatTopicToClient | RoomDemoPresenceTopicToClient,
    RoomDemoChatTopicToServer
  >(
    `/ws/rooms/${ROOM}?as=${encodeURIComponent(who)}`,
    [CHAT, PRESENCE],
    (message) => {
      // The generated union narrows on `action`, so each branch below knows its
      // payload shape without a cast.
      switch (message.action) {
        case 'chat_backlog':
          setEntries(message.payload.entries);
          break;
        case 'chat_message':
          setEntries((current) => [...current, message.payload]);
          break;
        case 'presence_state':
          setMembers(message.payload.members);
          break;
        case 'presence_join':
          setMembers((current) =>
            current.some((member) => member.id === message.payload.member.id)
              ? current
              : [...current, message.payload.member],
          );
          break;
        case 'presence_leave':
          setMembers((current) =>
            current.filter((member) => member.id !== message.payload.member.id),
          );
          break;
      }
    },
  );

  const post = () => {
    if (!draft.trim()) return;
    send(CHAT, { action: 'chat_send', payload: { body: draft } });
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
