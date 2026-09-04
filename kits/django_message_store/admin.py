from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import ChatEntryRecord


@admin.register(ChatEntryRecord)
class ChatEntryRecordAdmin(admin.ModelAdmin[ChatEntryRecord]):
    """Browse and search history. Read-only: an edit here could never reach clients
    that already received the message."""

    list_display = ["room", "author_id", "body", "sent_at"]
    list_filter = ["room"]
    search_fields = ["body", "author_id", "author_name", "entry_id"]
    date_hierarchy = "sent_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
