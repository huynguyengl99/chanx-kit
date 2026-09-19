"""Chanx messages carrying the AG-UI protocol: the protocol itself travels inside two
messages, one per direction, and clients switch on ``payload.type`` as they already do.
A third carries the one thing the protocol leaves to the transport — stopping a run."""

from typing import Literal

from chanx.messages.base import BaseMessage
from pydantic import BaseModel, ConfigDict, Field

from ag_ui.core import Event, RunAgentInput


class AgUiRunMessage(BaseMessage):
    """Client asks the agent to run; the payload is AG-UI's own ``RunAgentInput``."""

    action: Literal["ag_ui_run"] = "ag_ui_run"
    payload: RunAgentInput


class AgUiCancel(BaseModel):
    """Which run to stop. Named rather than implied, so a cancel that arrives after
    its run has ended cannot stop the one that replaced it."""

    # camelCase in, to match the protocol's own payloads on this socket. A
    # validation alias rather than a plain one, so the field keeps its Python name
    # when a server builds this message itself.
    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(validation_alias="runId")


class AgUiCancelMessage(BaseMessage):
    """Client asks for the run in flight to stop.

    AG-UI has no cancellation event: over SSE a client stops a run by dropping the
    HTTP request, which a shared, long-lived socket has no equivalent for. The
    protocol leaves this to the transport, so it is asked for explicitly here.
    """

    action: Literal["ag_ui_cancel"] = "ag_ui_cancel"
    payload: AgUiCancel


class AgUiEventMessage(BaseMessage):
    """One AG-UI event on its way to the client, as the protocol's ``Event`` union."""

    action: Literal["ag_ui_event"] = "ag_ui_event"
    payload: Event
