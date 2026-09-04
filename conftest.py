"""Test bootstrap: ``CHANX_KIT_BACKEND`` selects which chanx integration the suite
runs against, so the same kit tests execute once per backend."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

backend = os.environ.setdefault("CHANX_KIT_BACKEND", "fast_channels")

if backend == "channels":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.django_settings")

    import django

    django.setup()

    @pytest.fixture(autouse=True, scope="session")
    def _unblock_database(django_db_blocker: Any) -> Iterator[None]:
        # Channels runs close_old_connections on each connect; once any test opens a
        # connection, pytest-django's blocker would fail every later websocket test.
        with django_db_blocker.unblock():
            yield


VARIANT_FOR_BACKEND = {"channels": "django", "fast_channels": "fastapi"}

REGISTRY_INDEX = Path(__file__).parent / "copit-registry.json"


def _restricted_kit_paths() -> set[Path]:
    """Kit directories whose ``only_variants`` excludes the active backend."""
    if not REGISTRY_INDEX.exists():
        return set()

    variant = VARIANT_FOR_BACKEND.get(backend)
    index = json.loads(REGISTRY_INDEX.read_text())
    root = Path(__file__).parent

    return {
        root / component["path"]
        for component in index["components"].values()
        if component.get("only_variants") and variant not in component["only_variants"]
    }


RESTRICTED_KITS = _restricted_kit_paths()


def pytest_ignore_collect(collection_path: Path) -> bool | None:
    if any(
        collection_path == kit or kit in collection_path.parents
        for kit in RESTRICTED_KITS
    ):
        return True
    return None
