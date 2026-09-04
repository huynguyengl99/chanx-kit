from typing import Any

import pytest
from chanx.core.decorators import ws_handler
from chanx.messages.incoming import PingMessage
from chanx.messages.outgoing import PongMessage

from .. import (
    KitConsumer,
    assert_silent,
    build_app,
    communicator,
    detect_backend,
    receive_json,
    setup_memory_layer,
)

PATH = "/ws/echo/{name}"


class EchoConsumer(KitConsumer):
    channel_layer_alias = "default"

    @ws_handler(summary="Ping", description="Connection health check.")
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


@pytest.fixture(autouse=True)
def _layer() -> None:
    setup_memory_layer("default")


@pytest.fixture
def app() -> Any:
    return build_app({PATH: EchoConsumer})


async def test_build_app_and_communicator_serve_a_parametrised_route(app: Any) -> None:
    async with communicator(app, PATH, EchoConsumer, name="general") as comm:
        await comm.send_message(PingMessage())

        (reply,) = await receive_json(comm, 1)
        await assert_silent(comm)

    assert reply["action"] == "pong"


def test_missing_path_parameter_is_an_error(app: Any) -> None:
    with pytest.raises(KeyError, match="name"):
        communicator(app, PATH, EchoConsumer)


def test_env_override_pins_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANX_KIT_BACKEND", "fast_channels")
    assert detect_backend() == "fast_channels"

    monkeypatch.setenv("CHANX_KIT_BACKEND", "channels")
    assert detect_backend() == "channels"


def test_invalid_backend_override_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANX_KIT_BACKEND", "flask")
    with pytest.raises(ValueError, match="flask"):
        detect_backend()
