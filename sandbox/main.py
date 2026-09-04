"""Sandbox app mounting every kit. Run it with ``uv run python -m sandbox``, then open
http://localhost:8000 for the UI and /asyncapi for the generated WebSocket API docs."""

from pathlib import Path

from chanx.fast_channels import asyncapi_docs, asyncapi_spec_json, asyncapi_spec_yaml
from chanx.fast_channels.type_defs import AsyncAPIConfig
from fastapi import FastAPI, Response
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sandbox.consumers import AgentConsumer, NotificationConsumer, RoomConsumer
from sandbox.layers import setup_layers

setup_layers()

UI_DIST = Path(__file__).parent / "ui" / "dist"
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="ChanX Kit sandbox")

asyncapi_config = AsyncAPIConfig(
    description="WebSocket API exposed by the ChanX Kit sandbox.",
    version="0.1.0",
)


@app.get("/asyncapi", tags=["docs"], include_in_schema=False)
async def asyncapi_documentation(request: Request) -> HTMLResponse:
    return await asyncapi_docs(request=request, app=app, config=asyncapi_config)


@app.get("/asyncapi.json", tags=["docs"])
async def asyncapi_json(request: Request) -> JSONResponse:
    return await asyncapi_spec_json(request=request, app=app, config=asyncapi_config)


@app.get("/asyncapi.yaml", tags=["docs"])
async def asyncapi_yaml(request: Request) -> Response:
    return await asyncapi_spec_yaml(request=request, app=app, config=asyncapi_config)


ws = FastAPI()
ws.router.add_websocket_route("/notifications", NotificationConsumer.as_asgi())
ws.router.add_websocket_route("/rooms/{room}", RoomConsumer.as_asgi())
ws.router.add_websocket_route("/agent", AgentConsumer.as_asgi())
app.mount("/ws", ws)

if UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
else:

    @app.get("/", include_in_schema=False)
    async def ui_not_built() -> FileResponse:
        return FileResponse(STATIC / "index.html")
