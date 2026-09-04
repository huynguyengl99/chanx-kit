"""Minimal Django settings so kit tests can run against the Channels backend."""

SECRET_KEY = "chanx-kit-test-only"  # noqa: S105
DEBUG = True
USE_TZ = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "channels",
    "rest_framework",
    # Django-only kits are apps. They are only collected on this backend; see the
    # pytest_ignore_collect hook in the root conftest.
    "kits.django_message_store",
]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

ROOT_URLCONF = "tests.django_urls"
