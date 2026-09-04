"""Backend-agnostic test harness: hides the consumer base class, route declaration
and in-memory channel layer registration, so one kit test suite runs against both
Django Channels and FastAPI / fast-channels."""

import os
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    # Resolved at runtime by __getattr__; pinned here so kit tests keep type inference.
    from chanx.fast_channels.websocket import (
        AsyncJsonWebsocketConsumer as KitConsumer,
    )

    __all__ = ["KitConsumer"]

Backend = Literal["channels", "fast_channels"]

_PARAM = re.compile(r"\{(\w+)\}")
_ENV_VAR = "CHANX_KIT_BACKEND"


def detect_backend() -> Backend:
    """Return the chanx backend to test against.

    Honours ``CHANX_KIT_BACKEND``; otherwise falls back to whichever integration
    is importable.
    """
    override = os.environ.get(_ENV_VAR)
    if override:
        if override not in ("channels", "fast_channels"):
            raise ValueError(
                f"{_ENV_VAR}={override!r} is not a valid backend "
                "(expected 'channels' or 'fast_channels')"
            )
        # mypy does not narrow the membership check above; pyright does.
        return cast("Backend", override)

    from chanx.utils.framework import detect_framework

    return cast("Backend", detect_framework())


def _consumer_base(backend: Backend | None = None) -> Any:
    """Return the chanx consumer base class for the active backend."""
    backend = backend or detect_backend()
    if backend == "fast_channels":
        from chanx.fast_channels.websocket import (  # noqa: PLC0415
            AsyncJsonWebsocketConsumer as Consumer,
        )
    else:
        from chanx.channels.websocket import (  # type: ignore[assignment]
            AsyncJsonWebsocketConsumer as Consumer,
        )
    return Consumer


def setup_memory_layer(alias: str = "default", backend: Backend | None = None) -> None:
    """Register a fresh in-memory channel layer under ``alias``.

    Call per test so group state never leaks between tests.
    """
    backend = backend or detect_backend()
    if backend == "fast_channels":
        from fast_channels.layers import InMemoryChannelLayer, register_channel_layer

        register_channel_layer(alias, InMemoryChannelLayer())
    else:
        # Channels builds layers lazily from settings; dropping the cached backend
        # is what gives the next test a clean layer.
        from channels.layers import channel_layers

        channel_layers.backends.pop(alias, None)


def build_app(routes: Mapping[str, Any], backend: Backend | None = None) -> Any:
    """Build an ASGI application exposing ``routes`` as WebSocket endpoints.

    ``routes`` maps a path template to a consumer class; ``{name}`` captures are
    translated to each backend's own syntax.
    """
    backend = backend or detect_backend()

    if backend == "fast_channels":
        from fastapi import FastAPI

        app = FastAPI()
        for path, consumer in routes.items():
            app.router.add_websocket_route(path, consumer.as_asgi())
        return app

    from channels.routing import URLRouter
    from django.urls import re_path

    return URLRouter(
        cast(
            "list[Any]",
            [
                re_path(_to_django_regex(path), consumer.as_asgi())
                for path, consumer in routes.items()
            ],
        )
    )


def communicator(
    app: Any,
    path: str,
    consumer: Any,
    backend: Backend | None = None,
    **params: Any,
) -> Any:
    """Open a chanx test communicator against ``path`` on ``app``.

    Path captures are supplied as keyword arguments.
    """
    backend = backend or detect_backend()
    url = _route_url(path, **params)

    if backend == "fast_channels":
        from chanx.fast_channels.testing import (
            WebsocketCommunicator as Communicator,
        )
    else:
        from chanx.channels.testing import (  # type: ignore[assignment]
            WebsocketCommunicator as Communicator,
        )

    return Communicator(app, url, consumer=consumer)


async def receive_json(
    comm: Any, count: int = 1, timeout: float = 1
) -> list[dict[str, Any]]:
    """Read exactly ``count`` messages.

    asgiref's test communicator cancels the running application when a read times
    out, so draining until timeout silently kills the connection. Read an expected
    number instead, and use :func:`assert_silent` to assert nothing further arrives.
    """
    return [await comm.receive_json_from(timeout) for _ in range(count)]


async def receive_until(
    comm: Any, action: str, timeout: float = 1, limit: int = 20
) -> dict[str, Any]:
    """Read messages until one with ``action`` arrives, and return it."""
    seen: list[str] = []
    for _ in range(limit):
        message = await comm.receive_json_from(timeout)
        if message.get("action") == action:
            return message
        seen.append(str(message.get("action")))
    raise AssertionError(f"No {action!r} message after {limit} messages; saw {seen}")


async def assert_silent(comm: Any, timeout: float = 0.2) -> None:
    """Assert no further message is queued, without killing the connection."""
    assert await comm.receive_nothing(timeout), "expected no further messages"


def _route_url(path: str, **params: Any) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise KeyError(f"Missing path parameter {name!r} for route {path!r}")
        return str(params[name])

    return _PARAM.sub(replace, path)


def __getattr__(name: str) -> Any:
    # Lazy so importing this module does not require a backend to be installed.
    if name == "KitConsumer":
        return _consumer_base()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _to_django_regex(path: str) -> str:
    pattern = _PARAM.sub(lambda m: f"(?P<{m.group(1)}>[^/]+)", path.lstrip("/"))
    return rf"^{pattern}$"
