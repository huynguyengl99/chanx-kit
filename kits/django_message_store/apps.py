from django.apps import AppConfig


class DjangoMessageStoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # Derived, because the kit is copied: its import path depends on the target
    # directory you installed it into, and a hardcoded one would only work here.
    name = __name__.rsplit(".", 1)[0]
    # Pinned so migrations keep the same app label wherever the kit is copied to.
    label = "django_message_store"
    verbose_name = "Chat history"
