from __future__ import annotations

from datetime import datetime

from django.db import models

from ..room_chat.messages import ChatAuthor, ChatEntry


class ChatEntryRecord(models.Model):
    """One chat message, as stored. ``ChatEntry`` stays the wire contract, so a schema
    change here cannot alter what clients receive."""

    entry_id: models.CharField[str, str] = models.CharField(max_length=32, unique=True)
    room: models.CharField[str, str] = models.CharField(max_length=255)
    author_id: models.CharField[str, str] = models.CharField(max_length=255)
    author_name: models.CharField[str, str] = models.CharField(
        max_length=255, blank=True
    )
    body: models.TextField[str, str] = models.TextField()
    sent_at: models.DateTimeField[datetime, datetime] = models.DateTimeField()

    class Meta:
        # Backlog reads are "latest N in this room"; the index carries the ordering.
        indexes = [models.Index(fields=["room", "-sent_at"])]
        ordering = ["-sent_at"]

    def __str__(self) -> str:
        return f"{self.room}: {self.body[:40]}"

    @classmethod
    def from_entry(cls, entry: ChatEntry) -> ChatEntryRecord:
        return cls(
            entry_id=entry.id,
            room=entry.room,
            author_id=entry.author.id,
            author_name=entry.author.name or "",
            body=entry.body,
            sent_at=entry.sent_at,
        )

    def to_entry(self) -> ChatEntry:
        return ChatEntry(
            id=self.entry_id,
            room=self.room,
            body=self.body,
            author=ChatAuthor(id=self.author_id, name=self.author_name or None),
            sent_at=self.sent_at,
        )
