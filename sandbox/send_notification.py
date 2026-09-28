"""Push a notification from outside the web process: no WebSocket, no consumer, just
the topic. Needs REDIS_URL (in ``.env``), since an in-memory layer cannot cross processes.

    uv run python -m sandbox.send_notification "Build finished"
    uv run python -m sandbox.send_notification --user chris "Just for you"

Publishes through the classes consumers.py mounts: group names are namespaced by class
name, so a different class would address a group nobody joined and fail silently.
"""

import argparse
import asyncio
import os

from kits.notification import BroadcastNotificationTopic, NotificationPayload

from sandbox.consumers import DemoUserNotificationTopic
from sandbox.env import load_env
from sandbox.layers import setup_layers


async def main() -> None:
    parser = argparse.ArgumentParser(prog="sandbox.send_notification")
    parser.add_argument("title", nargs="*", help="notification title")
    parser.add_argument(
        "--user", help="address one user instead of everyone, e.g. --user chris"
    )
    args = parser.parse_args()

    load_env()
    if not os.environ.get("REDIS_URL"):
        raise SystemExit(
            "REDIS_URL is not set. The sandbox falls back to an in-memory channel "
            "layer, which cannot cross process boundaries, so this script would "
            "publish into its own layer and nothing would reach the browser.\n"
            "Run `docker compose up -d`, set REDIS_URL in .env (see .env.example), "
            "and restart the server so both use it."
        )

    setup_layers()

    title = " ".join(args.title) or "Hello from a worker"
    payload = NotificationPayload(title=title, body="sent from a separate process")

    if args.user:
        await DemoUserNotificationTopic.notify_user(args.user, payload)
        print(f"Sent {title!r} to user {args.user!r}")
    else:
        await BroadcastNotificationTopic.notify_all(payload)
        print(f"Sent {title!r} to everyone")


if __name__ == "__main__":
    asyncio.run(main())
