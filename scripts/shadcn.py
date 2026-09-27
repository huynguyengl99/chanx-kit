#!/usr/bin/env python
"""Emit the UI kits as a shadcn registry (React variant), served with the docs site.

python scripts/shadcn.py site/r [base-url]
"""

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "ui" / "copit-registry.json"
BASE_URL = "https://huynguyengl99.github.io/chanx-kit/r"
# `~` is the project root in shadcn; matches copit's `src/chanx-kit` target.
TARGET = "~/src/chanx-kit"


def item(component: dict[str, Any], base_url: str = BASE_URL) -> dict[str, Any]:
    name = component["name"]
    root = REPO_ROOT / component["path"]
    return {
        "$schema": "https://ui.shadcn.com/schema/registry-item.json",
        "name": name,
        "type": "registry:block",
        "title": component["title"],
        "description": component["description"],
        "dependencies": component["dependencies"],
        "registryDependencies": [
            f"{base_url}/{dependency}.json" for dependency in component["requires"]
        ],
        "files": [
            {
                "path": f"{component['path']}/{file}",
                "type": "registry:file",
                "target": f"{TARGET}/{name}/{file}",
                "content": (root / file).read_text(),
            }
            for file in component["files"]
            if file != "README.md"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("base_url", nargs="?", default=BASE_URL)
    args = parser.parse_args()
    out: Path = args.out
    base_url: str = args.base_url
    out.mkdir(parents=True, exist_ok=True)

    index = json.loads(INDEX.read_text())
    items = [item(component, base_url) for component in index["components"].values()]
    for entry in items:
        (out / f"{entry['name']}.json").write_text(json.dumps(entry, indent=2) + "\n")

    registry = {
        "$schema": "https://ui.shadcn.com/schema/registry.json",
        "name": index["name"],
        "homepage": index["homepage"],
        "items": [
            {key: value for key, value in entry.items() if key != "$schema"}
            | {
                "files": [
                    {k: f[k] for k in ("path", "type", "target")}
                    for f in entry["files"]
                ]
            }
            for entry in items
        ],
    }
    (out / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")
    print(f"Wrote {len(items)} shadcn items to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
