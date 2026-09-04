#!/usr/bin/env python
"""Build and validate the component registry.

``copit-registry.json`` is generated from ``registry.yaml`` plus every
``kits/*/kit.yaml``, and committed so installs are a single HTTP GET and
contract changes show up in PR diffs.

    python scripts/registry.py build     # regenerate copit-registry.json
    python scripts/registry.py check     # validate, and fail if copit-registry.json is stale
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_YAML = REPO_ROOT / "registry.yaml"
REGISTRY_JSON = REPO_ROOT / "copit-registry.json"
# copit owns the index format; this is a vendored copy of its published schema.
SCHEMA = Path(__file__).resolve().parent / "registry.schema.json"

REQUIRED_FILES = ("__init__.py", "README.md")
SCHEMA_VERSION = 1


@dataclass
class Problem:
    component: str | None
    message: str

    def __str__(self) -> str:
        where = f"{self.component}: " if self.component else ""
        return f"{where}{self.message}"


@dataclass
class Registry:
    config: dict[str, Any]
    components: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a mapping")
    return data


def matches(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def component_files(
    directory: Path, excludes: list[str], optional: dict[str, list[str]]
) -> tuple[list[str], dict[str, list[str]]]:
    """Split a component's files into what always ships and the optional groups."""
    files: list[str] = []
    groups: dict[str, list[str]] = {name: [] for name in optional}

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if any(part == "__pycache__" for part in path.parts):
            continue

        relative = path.relative_to(directory).as_posix()

        group = next(
            (
                name
                for name, patterns in optional.items()
                if matches(relative, patterns)
            ),
            None,
        )
        if group is not None:
            groups[group].append(relative)
            continue

        if matches(relative, excludes):
            continue

        files.append(relative)

    return files, {name: paths for name, paths in groups.items() if paths}


def optional_groups_for(
    group_files: dict[str, list[str]], declared: dict[str, Any]
) -> dict[str, Any]:
    """Shape each optional group for the index.

    A group is published as a bare file list unless the kit declares what those files
    need, in which case it becomes the object form copit resolves on ``--with``.
    """
    groups: dict[str, Any] = {}
    for group, paths in group_files.items():
        spec = declared.get(group) or {}
        requires = list(spec.get("requires", []))
        dependencies = list(spec.get("dependencies", []))
        if not requires and not dependencies:
            groups[group] = paths
            continue

        entry: dict[str, Any] = {"include": paths}
        if requires:
            entry["requires"] = requires
        if dependencies:
            entry["dependencies"] = dependencies
        groups[group] = entry
    return groups


def group_requires(component: dict[str, Any]) -> list[tuple[str, str]]:
    """``(dependency, group)`` pairs a component's optional groups pull in."""
    return [
        (dependency, group)
        for group, spec in component.get("optional", {}).items()
        if isinstance(spec, dict)
        for dependency in spec.get("requires", [])
    ]


def build() -> tuple[Registry, list[Problem]]:
    config = load_yaml(REGISTRY_YAML)
    problems: list[Problem] = []

    root = REPO_ROOT / str(config.get("root", "kits"))
    install = config.get("install", {})
    excludes = list(install.get("exclude", []))
    optional_groups: dict[str, list[str]] = {
        name: list(patterns)
        for name, patterns in (install.get("optional") or {}).items()
    }
    default_tier = str(config.get("default_tier", "contrib"))
    known_variants = set(config.get("variants", []))

    registry = Registry(config=config)
    seen_directories: dict[str, str] = {}

    for manifest in sorted(root.glob("*/kit.yaml")):
        directory = manifest.parent
        data = load_yaml(manifest)

        name = data.get("name")
        if not name:
            problems.append(Problem(directory.name, "kit.yaml has no 'name'"))
            continue
        name = str(name)

        expected_dir = name.replace("-", "_")
        if directory.name != expected_dir:
            problems.append(
                Problem(
                    name,
                    f"lives in {directory.name!r} but its id implies {expected_dir!r}; "
                    "the directory is the Python package name a user imports",
                )
            )

        if name in registry.components:
            problems.append(
                Problem(name, f"id is already used by {seen_directories[name]}")
            )
            continue
        seen_directories[name] = directory.name

        for required in REQUIRED_FILES:
            if not (directory / required).exists():
                problems.append(Problem(name, f"is missing {required}"))
        if not any((directory / "tests").glob("test_*.py")):
            problems.append(Problem(name, "has no tests/test_*.py"))

        variants = data.get("variants") or {}
        only_variants = list(data.get("only_variants", []))
        for variant in [*variants, *only_variants]:
            if variant not in known_variants:
                problems.append(
                    Problem(
                        name,
                        f"declares unknown variant {variant!r}; "
                        f"registry.yaml allows {sorted(known_variants)}",
                    )
                )

        files, group_files = component_files(directory, excludes, optional_groups)
        declared = data.get("optional") or {}
        for group in declared:
            if group not in optional_groups:
                problems.append(
                    Problem(
                        name,
                        f"declares unknown optional group {group!r}; "
                        f"registry.yaml allows {sorted(optional_groups)}",
                    )
                )
        optional = optional_groups_for(group_files, declared)

        registry.components[name] = {
            "name": name,
            "title": data.get("title", name),
            "description": " ".join(str(data.get("description", "")).split()),
            "tier": str(data.get("tier", default_tier)),
            "version": str(data.get("version", "0.0.0")),
            "path": directory.relative_to(REPO_ROOT).as_posix(),
            "tags": list(data.get("tags", [])),
            "authors": list(data.get("authors", [])),
            "requires": list(data.get("requires", [])),
            "dependencies": list(data.get("dependencies", [])),
            "variants": variants,
            "only_variants": only_variants,
            "files": files,
            "optional": optional,
        }

    problems.extend(validate_graph(registry))
    return registry, problems


def validate_graph(registry: Registry) -> list[Problem]:
    problems: list[Problem] = []
    tier_rules: dict[str, list[str]] = registry.config.get("tier_rules", {})

    for name, component in registry.components.items():
        edges = [(dependency, "") for dependency in component["requires"]]
        edges += [
            (dependency, f" for the {group!r} group")
            for dependency, group in group_requires(component)
        ]

        for dependency, where in edges:
            target = registry.components.get(dependency)
            if target is None:
                problems.append(
                    Problem(name, f"requires unknown component {dependency!r}{where}")
                )
                continue

            allowed = tier_rules.get(component["tier"])
            if allowed is not None and target["tier"] not in allowed:
                problems.append(
                    Problem(
                        name,
                        f"is {component['tier']} and cannot depend on "
                        f"{dependency!r}{where} ({target['tier']}); "
                        f"{component['tier']} may depend on {allowed}",
                    )
                )

            # A kit depending on a restricted kit must be at least as restricted.
            required = set(target["only_variants"])
            restricted = set(component["only_variants"])
            if required and (not restricted or not restricted <= required):
                problems.append(
                    Problem(
                        name,
                        f"depends on {dependency!r}{where}, which is limited to "
                        f"{sorted(required)}, so it must declare "
                        f"only_variants within {sorted(required)}",
                    )
                )

    problems.extend(find_cycles(registry))
    return problems


def find_cycles(registry: Registry) -> list[Problem]:
    problems: list[Problem] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def walk(name: str, trail: list[str]) -> None:
        if name in done:
            return
        if name in visiting:
            cycle = " -> ".join([*trail, name])
            problems.append(Problem(None, f"dependency cycle: {cycle}"))
            return
        visiting.add(name)
        component = registry.components.get(name, {})
        edges = list(component.get("requires", []))
        edges += [dependency for dependency, _ in group_requires(component)]
        for dependency in edges:
            if dependency in registry.components:
                walk(dependency, [*trail, name])
        visiting.discard(name)
        done.add(name)

    for name in registry.components:
        walk(name, [])
    return problems


def serialise(registry: Registry) -> str:
    config = registry.config
    document = {
        "version": SCHEMA_VERSION,
        "name": config["name"],
        "title": config.get("title", config["name"]),
        "description": config.get("description", ""),
        "source": config["source"],
        "homepage": config.get("homepage"),
        "ecosystem": config.get("ecosystem", "python"),
        "variants": list(config.get("variants", [])),
        "install": config.get("install", {}),
        "components": dict(sorted(registry.components.items())),
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def schema_problems(document: dict[str, Any]) -> list[Problem]:
    """Validate the generated index against copit's published schema."""
    try:
        import jsonschema
    except (
        ModuleNotFoundError
    ):  # pragma: no cover - jsonschema is in the registry group
        return [Problem(None, "jsonschema is not installed; cannot validate the index")]

    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
    return [
        Problem(
            None,
            "copit-registry.json does not match copit's schema at "
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}",
        )
        for error in sorted(validator.iter_errors(document), key=lambda e: e.path)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "check"])
    args = parser.parse_args()

    registry, problems = build()

    if problems:
        print(f"Registry has {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    rendered = serialise(registry)

    schema_issues = schema_problems(json.loads(rendered))
    if schema_issues:
        print(
            f"Registry index is invalid ({len(schema_issues)} problem(s)):",
            file=sys.stderr,
        )
        for problem in schema_issues:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if args.command == "build":
        REGISTRY_JSON.write_text(rendered)
        print(f"Wrote {REGISTRY_JSON.name} with {len(registry.components)} components:")
        for name, component in registry.components.items():
            requires = component["requires"]
            suffix = f" -> requires {requires}" if requires else ""
            print(f"  {component['tier']:<8} {name}{suffix}")
        return 0

    current = REGISTRY_JSON.read_text() if REGISTRY_JSON.exists() else ""
    if current != rendered:
        print(
            "copit-registry.json is out of date. Run: python scripts/registry.py build",
            file=sys.stderr,
        )
        return 1

    print(f"Registry OK — {len(registry.components)} components.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
