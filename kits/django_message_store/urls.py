"""Router for the history API.

Include it wherever you like, e.g. in your project's ``urlpatterns``:
``path("api/chat/", include("app.ws_kits.django_message_store.urls"))``.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import RoomHistoryViewSet

router = DefaultRouter()
router.register("history", RoomHistoryViewSet, basename="chat-history")

urlpatterns = [path("", include(router.urls))]
