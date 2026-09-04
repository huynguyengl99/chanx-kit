"""Who is present in a scope, and telling everyone when that changes."""

from typing import Any, ClassVar

from chanx.core.decorators import ws_handler
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage
from chanx.utils.scope import scope_user

from .messages import (
    PresenceEventPayload,
    PresenceJoinMessage,
    PresenceLeaveMessage,
    PresenceMember,
    PresenceRequestMessage,
    PresenceStateMessage,
    PresenceStatePayload,
)
from .store import InMemoryPresenceStore, PresenceStore


class PresenceTopic(Topic[PresenceJoinMessage | PresenceLeaveMessage]):
    """Tracks who is present in a scope: ``presence:<scope>``.

    On subscribe the client receives a ``presence_state`` message with the full
    roster, then ``presence_join`` / ``presence_leave`` as it changes. A member with
    several connections open produces one join and one leave, not one per tab.

    Override :meth:`presence_member` to describe the member.
    """

    pattern = "presence:{scope}"

    passthrough_events: ClassVar[list[type[BaseMessage]]] = [
        PresenceJoinMessage,
        PresenceLeaveMessage,
    ]

    presence_store: ClassVar[PresenceStore] = InMemoryPresenceStore()

    @property
    def presence_scope(self) -> str:
        return self.params["scope"]

    def presence_member(self) -> PresenceMember:
        """Describe whoever is on the other end of this connection."""
        user: Any = scope_user(self.scope)
        if user is None:
            return PresenceMember(id=self.channel_name, name="anonymous")
        identifier = getattr(user, "pk", None) or getattr(user, "id", None)
        return PresenceMember(
            id=str(identifier or self.channel_name),
            name=str(getattr(user, "username", None) or identifier or "anonymous"),
        )

    async def on_subscribe(self) -> None:
        member = self.presence_member()
        newly_present = await self.presence_store.add(
            self.presence_scope, self.channel_name, member
        )

        await self.send_message(await self.presence_state())

        if newly_present:
            await self.announce_join(member)

    async def on_unsubscribe(self) -> None:
        departed = await self.presence_store.discard(
            self.presence_scope, self.channel_name
        )
        if departed is not None:
            await self.announce_leave(departed)

    async def presence_state(self) -> PresenceStateMessage:
        members = await self.presence_store.members(self.presence_scope)
        return PresenceStateMessage(
            payload=PresenceStatePayload(scope=self.presence_scope, members=members)
        )

    @ws_handler(
        summary="Request the roster",
        description="Return who is currently present, without reconnecting.",
    )
    async def handle_presence_request(
        self, _message: PresenceRequestMessage
    ) -> PresenceStateMessage:
        return await self.presence_state()

    async def announce_join(self, member: PresenceMember) -> None:
        await self.broadcast(
            self.topic,
            PresenceJoinMessage(
                payload=PresenceEventPayload(scope=self.presence_scope, member=member)
            ),
        )

    async def announce_leave(self, member: PresenceMember) -> None:
        await self.broadcast(
            self.topic,
            PresenceLeaveMessage(
                payload=PresenceEventPayload(scope=self.presence_scope, member=member)
            ),
        )

    @classmethod
    async def members_of(cls, scope: str) -> list[PresenceMember]:
        """Who is currently present in ``scope``, callable from anywhere."""
        return await cls.presence_store.members(scope)
