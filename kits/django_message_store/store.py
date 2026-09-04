"""Durable :class:`MessageStore` backed by the Django ORM."""

from ..room_chat.messages import ChatEntry
from ..room_chat.store import MessageStore
from .models import ChatEntryRecord


class DjangoMessageStore(MessageStore):
    """Chat history in your database. Survives restarts and is shared across workers."""

    async def append(self, entry: ChatEntry) -> None:
        await ChatEntryRecord.from_entry(entry).asave()

    async def backlog(self, room: str, limit: int) -> list[ChatEntry]:
        # Meta.ordering is newest-first so the limit takes the latest rows; clients
        # get them oldest-first, hence the reverse.
        records = [
            record async for record in ChatEntryRecord.objects.filter(room=room)[:limit]
        ]
        return [record.to_entry() for record in reversed(records)]
