"""Durable chat history for the room-chat kit, in your Django database.

Deliberately exports nothing: a Django app's ``__init__`` is imported before the app
registry is ready, so re-exporting the store (which pulls in ``models``) would raise
``AppRegistryNotReady``. Import ``DjangoMessageStore`` from ``.store`` instead.
"""
