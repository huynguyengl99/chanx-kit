import { ChatRoom, useChat } from '../chanx-kit/chat/react';
import { usePresence } from '../chanx-kit/presence/react';
import { room } from '../generated';

const ROOM = 'general';
const chat = room.topics.demoChatTopic.with({ room: ROOM });
const presence = room.topics.demoPresenceTopic.with({ scope: ROOM });

/** Two independent kits, chat and presence, over a single connection. */
export function RoomPanel({ who }: { who: string }) {
  // Same channel and connection options, so both hooks share one socket.
  const options = { params: { room: ROOM }, queryParams: { as: who } };
  const { entries, status, send } = useChat(room, chat, options);
  const { members } = usePresence(room, presence, options);

  return (
    <div className="stack">
      <ChatRoom
        title="Room · chat + presence"
        entries={entries}
        status={status}
        onSend={send}
        members={members}
        self={who}
      />
      <p className="hint">
        Open a second tab with a different name: history replays on connect and the
        roster updates live.
      </p>
    </div>
  );
}
