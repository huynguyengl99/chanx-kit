#!/usr/bin/env python
"""Build and validate the component registries.

Two registries share this repo: the server kits (``registry.yaml`` plus every
``kits/*/kit.yaml``, published as ``copit-registry.json``) and the UI kits
(``ui/registry.yaml`` plus ``ui/*/kit.yaml``, published as ``ui/copit-registry.json``).
Both indexes are committed so installs are a single HTTP GET and changes show up in
PR diffs. Contracts (``defines`` / ``implements`` / ``consumes``) are checked across
the two, and stay out of the indexes.

    python scripts/registry.py build     # regenerate both indexes
    python scripts/registry.py check     # validate, and fail if an index is stale
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
# copit owns the index format; this is a vendored copy of its published schema.
SCHEMA = Path(__file__).resolve().parent / "registry.schema.json"

SCHEMA_VERSION = 1
CONTRACT = re.compile(r"^[a-z][a-z0-9-]*@[1-9][0-9]*$")


@dataclass(frozen=True)
class Layout:
    """What one registry's components look like on disk."""

    manifest: Path
    index: Path
    required_files: tuple[str, ...]
    test_glob: str
    # A Python kit's directory is the package name a user imports.
    underscore_dirs: bool


SERVER = Layout(
    manifest=REPO_ROOT / "registry.yaml",
    index=REPO_ROOT / "copit-registry.json",
    required_files=("__init__.py", "README.md"),
    test_glob="tests/test_*.py",
    underscore_dirs=True,
)
UI = Layout(
    manifest=REPO_ROOT / "ui" / "registry.yaml",
    index=REPO_ROOT / "ui" / "copit-registry.json",
    required_files=("README.md", "core.ts", "index.ts"),
    test_glob="tests/*.test.ts",
    underscore_dirs=False,
)
LAYOUTS = (SERVER, UI)


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
    # Kept out of the published index.
    contracts: dict[str, dict[str, Any]] = field(default_factory=dict)
    layout: Layout = SERVER


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


def expand_variants(variants: dict[str, Any], files: list[str]) -> dict[str, Any]:
    """Resolve each variant's ``include`` globs to the component's actual files."""
    expanded: dict[str, Any] = {}
    for variant, spec in variants.items():
        entry = dict(spec or {})
        if "include" in entry:
            entry["include"] = [
                file for file in files if matches(file, list(entry["include"]))
            ]
        expanded[variant] = entry
    return expanded


def build_parts(
    name: str, data: dict[str, Any], files: list[str], group_files: dict[str, list[str]]
) -> tuple[dict[str, Any], list[Problem]]:
    """A kit's parts for the index; all a part lists must be on the kit, for copit < 0.9."""
    declared: dict[str, Any] = data.get("parts") or {}
    every_file = [*files, *(f for paths in group_files.values() for f in paths)]
    problems: list[Problem] = []
    parts: dict[str, Any] = {}
    for part, raw in declared.items():
        spec: dict[str, Any] = raw or {}
        include = [f for f in every_file if matches(f, list(spec.get("include", [])))]
        for pattern in spec.get("include", []):
            if not any(fnmatch.fnmatch(f, pattern) for f in every_file):
                problems.append(
                    Problem(
                        name,
                        f"part {part!r} includes {pattern!r}, which matches no file",
                    )
                )
        for key in ("requires", "dependencies", "implements"):
            missing = set(spec.get(key) or []) - set(data.get(key) or [])
            if missing:
                problems.append(
                    Problem(
                        name,
                        f"part {part!r} lists {key} {sorted(missing)} the kit does not; "
                        "a copit without parts would install the kit without them",
                    )
                )
        entry: dict[str, Any] = {"include": include}
        for key in ("requires", "dependencies"):
            if spec.get(key):
                entry[key] = list(spec[key])
        parts[part] = entry
    return parts, problems


def build(layout: Layout = SERVER) -> tuple[Registry, list[Problem]]:
    config = load_yaml(layout.manifest)
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

    registry = Registry(layout=layout, config=config)
    seen_directories: dict[str, str] = {}

    for manifest in sorted(root.glob("*/kit.yaml")):
        directory = manifest.parent
        data = load_yaml(manifest)

        name = data.get("name")
        if not name:
            problems.append(Problem(directory.name, "kit.yaml has no 'name'"))
            continue
        name = str(name)

        expected_dir = name.replace("-", "_") if layout.underscore_dirs else name
        if directory.name != expected_dir:
            problems.append(
                Problem(
                    name,
                    f"lives in {directory.name!r} but its id implies {expected_dir!r}",
                )
            )

        if name in registry.components:
            problems.append(
                Problem(name, f"id is already used by {seen_directories[name]}")
            )
            continue
        seen_directories[name] = directory.name

        for required in layout.required_files:
            if not (directory / required).exists():
                problems.append(Problem(name, f"is missing {required}"))
        if data.get("consumes") and not (directory / "contract.ts").exists():
            problems.append(Problem(name, "consumes a contract but has no contract.ts"))
        if not any(directory.glob(layout.test_glob)):
            problems.append(Problem(name, f"has no {layout.test_glob}"))

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
        variants = expand_variants(variants, files)
        parts, part_problems = build_parts(name, data, files, group_files)
        problems.extend(part_problems)
        registry.contracts[name] = {
            key: data[key]
            for key in ("defines", "contract_topic", "implements", "consumes")
            if key in data
        }

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
            **({"parts": parts} if parts else {}),
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


def contract_problems(server: Registry, ui: Registry) -> list[Problem]:
    """Every ``implements`` / ``consumes`` names a contract a server kit defines."""
    problems: list[Problem] = []
    defined: dict[str, str] = {}

    for name, meta in server.contracts.items():
        contract = meta.get("defines")
        if contract is None:
            if "contract_topic" in meta:
                problems.append(Problem(name, "has contract_topic but defines nothing"))
            continue
        if not CONTRACT.match(str(contract)):
            problems.append(
                Problem(name, f"defines {contract!r}; expected name@version")
            )
        if not meta.get("contract_topic"):
            problems.append(
                Problem(name, f"defines {contract} but names no contract_topic")
            )
        if contract in defined:
            problems.append(
                Problem(
                    name, f"defines {contract}, already defined by {defined[contract]}"
                )
            )
        defined[str(contract)] = name

    names = {contract.split("@")[0]: contract for contract in defined}

    def check(registry: Registry, key: str) -> None:
        for name, meta in registry.contracts.items():
            for contract in meta.get(key) or []:
                if contract in defined:
                    continue
                current = names.get(str(contract).split("@")[0])
                hint = f"; the current version is {current}" if current else ""
                problems.append(
                    Problem(name, f"{key} {contract!r}, which no kit defines{hint}")
                )

    check(server, "implements")
    check(ui, "consumes")
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
        **({"detect": config["detect"]} if config.get("detect") else {}),
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
            "the index does not match copit's schema at "
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}",
        )
        for error in sorted(validator.iter_errors(document), key=lambda e: e.path)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "check"])
    args = parser.parse_args()

    registries: list[Registry] = []
    problems: list[Problem] = []
    for layout in LAYOUTS:
        registry, found = build(layout)
        registries.append(registry)
        problems.extend(found)
    problems.extend(contract_problems(*registries))

    if problems:
        print(f"Registry has {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    status = 0
    for registry in registries:
        status |= publish(registry, args.command)
    return status


def publish(registry: Registry, command: str) -> int:
    index = registry.layout.index
    label = index.relative_to(REPO_ROOT).as_posix()
    rendered = serialise(registry)

    schema_issues = schema_problems(json.loads(rendered))
    if schema_issues:
        print(
            f"{label} is invalid ({len(schema_issues)} problem(s)):",
            file=sys.stderr,
        )
        for problem in schema_issues:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if command == "build":
        index.write_text(rendered)
        print(f"Wrote {label} with {len(registry.components)} components:")
        for name, component in registry.components.items():
            requires = component["requires"]
            suffix = f" -> requires {requires}" if requires else ""
            print(f"  {component['tier']:<8} {name}{suffix}")
        return 0

    current = index.read_text() if index.exists() else ""
    if current != rendered:
        print(
            f"{label} is out of date. Run: python scripts/registry.py build",
            file=sys.stderr,
        )
        return 1

    print(f"{label} OK — {len(registry.components)} components.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
