#!/usr/bin/env python
"""Check the feature recipes and every ``copit add`` in the docs against both registries.

uv run python scripts/recipes.py check
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RECIPES = REPO_ROOT / "docs" / "recipes.yaml"
SERVER, UI = "@chanx-kit/", "@chanx-kit-ui/"
# Where users read install commands.
DOCS = [
    "README.md",
    "docs/*.md",
    "kits/README.md",
    "kits/*/README.md",
    "ui/*/README.md",
    "templates/*/README.md",
]


def _components(index: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / index).read_text())["components"]


def _manifests(components: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: yaml.safe_load((REPO_ROOT / c["path"] / "kit.yaml").read_text())
        for name, c in components.items()
    }


SERVER_KITS = _manifests(_components("copit-registry.json"))
UI_KITS = _manifests(_components("ui/copit-registry.json"))


@dataclass
class Command:
    server: list[str] = field(default_factory=list)
    ui: list[str] = field(default_factory=list)
    only: list[str] = field(default_factory=list)
    without: list[str] = field(default_factory=list)


def parse(command: str) -> Command:
    parsed = Command()
    tokens = shlex.split(command.split("#", 1)[0])
    for i, token in enumerate(tokens):
        match token:
            case _ if token.startswith(SERVER):
                parsed.server.append(token.removeprefix(SERVER))
            case _ if token.startswith(UI):
                parsed.ui.append(token.removeprefix(UI))
            case "--only" | "--without" if i + 1 < len(tokens):
                value = tokens[i + 1]
                if not value.startswith("<"):
                    target = parsed.only if token == "--only" else parsed.without
                    target.extend(value.split(","))
            case _:
                pass
    return parsed


def kept_parts(meta: dict[str, Any], command: Command) -> set[str] | None:
    """The parts of a kit this command keeps, or None when it has none."""
    parts = set(meta.get("parts") or {})
    if not parts:
        return None
    kept = parts & set(command.only) if command.only else parts
    return kept - set(command.without)


def provided(name: str, command: Command | None = None) -> set[str]:
    """Contracts a server kit and what it requires provide, honouring parts."""
    meta = SERVER_KITS[name]
    contracts = {meta["defines"]} if meta.get("defines") else set()
    requires = set(meta.get("requires") or [])
    implements = set(meta.get("implements") or [])
    kept = kept_parts(meta, command) if command else None
    if kept is not None:
        parts = meta["parts"]
        implements = {c for p in kept for c in parts[p].get("implements") or []}
        dropped = {r for p in set(parts) - kept for r in parts[p].get("requires") or []}
        requires -= dropped - {r for p in kept for r in parts[p].get("requires") or []}
    contracts |= implements
    for required in requires:
        contracts |= provided(required)
    return contracts


def needed(name: str) -> set[str]:
    """Contracts a UI kit and what it requires consume."""
    meta = UI_KITS[name]
    contracts = set(meta.get("consumes") or [])
    for required in meta.get("requires") or []:
        contracts |= needed(required)
    return contracts


def command_problems(command: str) -> list[str]:
    parsed = parse(command)
    problems = [f"no server kit {k!r}" for k in parsed.server if k not in SERVER_KITS]
    problems += [f"no UI kit {k!r}" for k in parsed.ui if k not in UI_KITS]
    offered = {
        part
        for kit in parsed.server
        if kit in SERVER_KITS
        for part in SERVER_KITS[kit].get("parts") or {}
    }
    problems += [
        f"no requested kit has a part {p!r}"
        for p in [*parsed.only, *parsed.without]
        if p not in offered
    ]
    return problems


def recipe_problems(recipe: dict[str, Any]) -> list[str]:
    command = recipe["add"]
    problems = command_problems(command)
    if problems:
        return problems
    parsed = parse(command)
    have = set[str]().union(*(provided(kit, parsed) for kit in parsed.server))
    for ui in parsed.ui:
        for contract in sorted(needed(ui) - have):
            problems.append(f"{ui} needs {contract}, which no server kit here provides")
    for provider in recipe.get("providers") or []:
        swapped = command.replace(f"{SERVER}{parsed.server[-1]}", f"{SERVER}{provider}")
        problems += [f"with {provider}: {p}" for p in recipe_problems({"add": swapped})]
    return problems


def load() -> list[dict[str, Any]]:
    return yaml.safe_load(RECIPES.read_text())


def doc_commands() -> list[tuple[str, str]]:
    """Every ``copit add`` naming this registry, with where it is."""
    found: list[tuple[str, str]] = []
    for pattern in DOCS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                for match in re.finditer(r"copit add ([^`\n|]+)", line):
                    if SERVER in match[1] or UI in match[1]:
                        found.append(
                            (f"{path.relative_to(REPO_ROOT)}:{number}", match[1])
                        )
    return found


def check() -> list[str]:
    problems = [
        f"recipe {r['title']!r}: {p}" for r in load() for p in recipe_problems(r)
    ]
    for where, command in doc_commands():
        if "{" not in command:
            problems += [f"{where}: {p}" for p in command_problems(command)]
    readme = (REPO_ROOT / "README.md").read_text()
    problems += [
        f"README.md does not list the {r['title']!r} recipe: copit add {r['add']}"
        for r in load()
        if f"copit add {r['add']}" not in readme
    ]
    return problems


def main() -> int:
    if sys.argv[1:] != ["check"]:
        print(__doc__)
        return 2
    problems = check()
    for problem in problems:
        print(problem)
    print("Recipes OK." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
