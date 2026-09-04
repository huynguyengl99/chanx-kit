"""Launch the sandbox: ``uv run python -m sandbox``.

Serves the FastAPI app with every kit mounted, plus the built demo UI if there is one.

    uv run python -m sandbox                 # http://localhost:8000
    REDIS_URL=redis://localhost:6399/0 uv run python -m sandbox

Set REDIS_URL to broadcast across processes; the in-memory default cannot leave this
one. See sandbox/README.md for the UI dev server.
"""

import argparse
import os
from pathlib import Path

UI_DIST = Path(__file__).parent / "ui" / "dist"


def main() -> int:
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
