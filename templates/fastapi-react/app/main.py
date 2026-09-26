"""Run with ``uv run uvicorn app.main:app --reload``."""

from pathlib import Path

from chanx.fast_channels import asyncapi_docs, asyncapi_spec_json
from chanx.fast_channels.type_defs import AsyncAPIConfig
from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.consumers import AppUserNotificationTopic, NotificationConsumer
from app.layers import setup_layers
from app.ws_kits.notification import BroadcastNotificationTopic, NotificationPayload

setup_layers()

WEB_DIST = Path(__file__).parent.parent / "web" / "dist"

app = FastAPI(title="chanx app")

asyncapi_config = AsyncAPIConfig(
    description="WebSocket API of this app.", version="0.1.0"
)


@app.get("/asyncapi", include_in_schema=False)
async def asyncapi_documentation(request: Request) -> HTMLResponse:
    return await asyncapi_docs(request=request, app=app, config=asyncapi_config)


@app.get("/asyncapi.json")
async def asyncapi_json(request: Request) -> JSONResponse:
    return await asyncapi_spec_json(request=request, app=app, config=asyncapi_config)


class NotifyRequest(BaseModel):
    title: str
    body: str | None = None
    user: str | None = None


@app.post("/api/notify")
async def notify(request: NotifyRequest) -> dict[str, str]:
    payload = NotificationPayload(title=request.title, body=request.body)
    if request.user:
        await AppUserNotificationTopic.notify_user(request.user, payload)
        return {"sent_to": request.user}
    await BroadcastNotificationTopic.notify_all(payload)
    return {"sent_to": "everyone"}


ws = FastAPI()
ws.router.add_websocket_route("/notifications", NotificationConsumer.as_asgi())
app.mount("/ws", ws)

# Serves the built UI (`npm --prefix web run build`).
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
