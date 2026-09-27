"""Bytes in Python, standard base64 on the wire."""

import base64
import binascii
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema


def _to_bytes(value: Any) -> bytes:
    # Base64Bytes decodes raw bytes too, corrupting audio built in Python.
    if isinstance(value, bytes | bytearray):
        return bytes(value)
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except binascii.Error as error:
            raise ValueError(f"not valid base64: {error}") from error
    raise TypeError("expected bytes or a base64 string")


Base64Data = Annotated[
    bytes,
    BeforeValidator(_to_bytes),
    PlainSerializer(
        lambda data: base64.b64encode(data).decode("ascii"),
        return_type=str,
        when_used="json",
    ),
    WithJsonSchema({"type": "string", "format": "base64", "contentEncoding": "base64"}),
]
"""Binary data a handler sees as ``bytes`` and the wire carries as standard base64."""
