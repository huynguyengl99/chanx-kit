"""Redis when REDIS_URL is set, so presence and chat stay correct across workers, and
an in-memory layer otherwise so the demo runs with nothing installed."""

import os

from fast_channels.layers import (
    InMemoryChannelLayer,
    has_layers,
    register_channel_layer,
)

ALIAS = "default"


def setup_layers(force: bool = False) -> None:
    if has_layers() and not force:
        return

    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        from fast_channels.layers.redis import RedisPubSubChannelLayer

        register_channel_layer(
            ALIAS, RedisPubSubChannelLayer(hosts=[redis_url], prefix="chanx-kit")
        )
    else:
        register_channel_layer(ALIAS, InMemoryChannelLayer())
