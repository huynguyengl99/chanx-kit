"""Launch the sandbox: ``uv run python -m sandbox``.

Serves the FastAPI app with every kit mounted, plus the built demo UI if there is one.

    uv run python -m sandbox                 # http://localhost:8000

REDIS_URL and provider keys come from the environment or the git-ignored ``.env`` (see
``.env.example``). Without REDIS_URL the in-memory layer cannot leave this process. See
sandbox/README.md for the UI dev server.
"""

import argparse
import os
from pathlib import Path

from sandbox.env import load_env

UI_DIST = Path(__file__).parent / "ui" / "dist"


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="sandbox", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    args = parser.parse_args()

    import uvicorn

    banner = [
        "",
        f"  ChanX Kit sandbox   http://{args.host}:{args.port}",
        f"  AsyncAPI docs       http://{args.host}:{args.port}/asyncapi",
        "",
        "  channel layer       "
        + (
            f"redis ({os.environ['REDIS_URL']})"
            if os.environ.get("REDIS_URL")
            else "in-memory (single process; set REDIS_URL to share)"
        ),
        "  speech to text      "
        + ("deepgram" if os.environ.get("DEEPGRAM_API_KEY") else "fake"),
        "  text to speech      "
        + ("elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "fake"),
        "  demo UI             "
        + (
            "built"
            if UI_DIST.is_dir()
            else "not built. Run: npm --prefix sandbox/ui install && "
            "npm --prefix sandbox/ui run gen && npm --prefix sandbox/ui run build"
        ),
        "",
    ]
    print("\n".join(banner))

    uvicorn.run(
        "sandbox.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
