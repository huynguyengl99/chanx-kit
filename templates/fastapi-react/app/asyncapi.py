"""Print the AsyncAPI schema in-process, for ``npm --prefix web run gen``."""

import json

from chanx.fast_channels.views import generate_asyncapi_schema
from starlette.requests import Request

from app.main import app, asyncapi_config

# The schema's server address comes from the request.
request = Request(
    {
        "type": "http",
        "scheme": "http",
        "server": ("localhost", 8000),
        "path": "/",
        "headers": [],
    }
)
print(json.dumps(generate_asyncapi_schema(request, app, asyncapi_config), indent=2))
