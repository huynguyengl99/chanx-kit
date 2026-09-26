"""Redis when REDIS_URL is set (needed across processes), in-memory otherwise."""

import os

from fast_channels.layers import (
    InMemoryChannelLayer,
    has_layers,
    register_channel_layer,
)

ALIAS = "default"


def setup_layers() -> None:
    if has_layers():
        return

    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        from fast_channels.layers.redis import RedisPubSubChannelLayer

        register_channel_layer(
            ALIAS, RedisPubSubChannelLayer(hosts=[redis_url], prefix="chanx-app")
        )
    else:
        register_channel_layer(ALIAS, InMemoryChannelLayer())
