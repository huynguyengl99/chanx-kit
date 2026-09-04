from django.db.models import QuerySet
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination

from .models import ChatEntryRecord
from .serializers import ChatEntrySerializer


class HistoryPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class RoomHistoryViewSet(viewsets.ReadOnlyModelViewSet[ChatEntryRecord]):
    """Read-only history, newest first, filtered by ``?room=``. A POST here would
    persist a message that no live client is told about."""

    serializer_class = ChatEntrySerializer
    pagination_class = HistoryPagination
    lookup_field = "entry_id"

    def get_queryset(self) -> QuerySet[ChatEntryRecord]:
        queryset = ChatEntryRecord.objects.all()
        room = self.request.query_params.get("room")
        return queryset.filter(room=room) if room else queryset
