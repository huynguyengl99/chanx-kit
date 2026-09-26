"""Send a notification from another process. Needs the server's REDIS_URL.

REDIS_URL=redis://localhost:6399/0 uv run python -m app.notify --user ana "Hi"
"""

import argparse
import asyncio
import os

from app.consumers import AppUserNotificationTopic
from app.layers import setup_layers
from app.ws_kits.notification import BroadcastNotificationTopic, NotificationPayload


async def main() -> None:
    parser = argparse.ArgumentParser(prog="app.notify")
    parser.add_argument("title", nargs="*", help="notification title")
    parser.add_argument("--user", help="address one user instead of everyone")
    args = parser.parse_args()

    if not os.environ.get("REDIS_URL"):
        raise SystemExit(
            "REDIS_URL is not set: an in-memory layer cannot reach the server. "
            "Use the same REDIS_URL as the server."
        )

    setup_layers()
    title = " ".join(args.title) or "Hello from another process"
    payload = NotificationPayload(title=title, body="sent from app.notify")

    if args.user:
        await AppUserNotificationTopic.notify_user(args.user, payload)
    else:
        await BroadcastNotificationTopic.notify_all(payload)
    print(f"Sent {title!r} to {args.user or 'everyone'}")


if __name__ == "__main__":
    asyncio.run(main())
