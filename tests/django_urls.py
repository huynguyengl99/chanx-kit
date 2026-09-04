"""URLs for the Channels test run: the history API kits ship, mounted for tests."""

from django.urls import include, path

urlpatterns = [
    path("api/chat/", include("kits.django_message_store.urls")),
]
