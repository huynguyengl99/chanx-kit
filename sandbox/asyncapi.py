"""Print the sandbox's AsyncAPI schema, which the UI generates its client from."""

from fastapi.testclient import TestClient

from sandbox.main import app

print(TestClient(app).get("/asyncapi.json").text)
