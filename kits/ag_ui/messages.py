"""Chanx messages carrying the AG-UI protocol: the whole protocol travels inside two
messages, one per direction, and clients switch on ``payload.type`` as they already do."""

from typing import Literal

from chanx.messages.base import BaseMessage

from ag_ui.core import Event, RunAgentInput


class AgUiRunMessage(BaseMessage):
    """Client asks the agent to run; the payload is AG-UI's own ``RunAgentInput``."""

    action: Literal["ag_ui_run"] = "ag_ui_run"
    payload: RunAgentInput


class AgUiEventMessage(BaseMessage):
    """One AG-UI event on its way to the client, as the protocol's ``Event`` union."""

    action: Literal["ag_ui_event"] = "ag_ui_event"
    payload: Event
