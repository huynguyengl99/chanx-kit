from typing import Any

from rest_framework import serializers

from .models import ChatEntryRecord


class ChatEntrySerializer(serializers.Serializer[ChatEntryRecord]):
    """Read shape for the history API. Fields are declared, not derived with
    ``ModelSerializer``, so a model change cannot quietly re-shape the endpoint."""

    # The kit's entry id, not the database pk, so clients can match websocket messages.
    id = serializers.CharField(source="entry_id", read_only=True)
    room = serializers.CharField(read_only=True)
    body = serializers.CharField(read_only=True)
    sent_at = serializers.DateTimeField(read_only=True)
    author = serializers.SerializerMethodField()

    def get_author(self, obj: ChatEntryRecord) -> dict[str, Any]:
        return {"id": obj.author_id, "name": obj.author_name or None}
