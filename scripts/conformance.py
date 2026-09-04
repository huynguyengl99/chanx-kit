#!/usr/bin/env python
"""Install every kit with copit into a throwaway project, then import the result —
catching cross-kit imports that only resolve in this repo's layout, metadata leaking
into installs, missing `__init__.py`, or undeclared dependencies.

Requires copit {minimum} or newer, which is what resolves the components an optional
group needs.

    python scripts/conformance.py
    python scripts/conformance.py --keep     # leave the temp project for inspection
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_JSON = REPO_ROOT / "copit-registry.json"
TARGET = "app/ws_kits"

PYPROJECT = """\
[project]
name = "conformance"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = []

[tool.uv]
"""


# Kits declare the test harness under their `tests` group, which older copit ignores:
# it would install the kits happily and only the harness would be missing.
MINIMUM_COPIT = (0, 6)

TOO_OLD_NOTE = """\
This check needs copit {minimum} or newer, but found {version}.

Kits declare the chanx-testing harness under their `tests` optional group, and resolving
that is a 0.6 feature. An older copit installs everything without complaint and leaves
the harness out, which is exactly what this check exists to catch.

  uv sync                       # the `registry` group pins a new enough copit

To run against a local copit build, point COPIT at the binary. PATH will not work under
`uv run`, which puts the project venv's bin first:

  COPIT=/path/to/copit/target/release/copit uv run python scripts/conformance.py
"""


def copit_version(copit: str) -> str:
    result = subprocess.run(
        [copit, "--version"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "unknown"


def version_tuple(reported: str) -> tuple[int, ...]:
    """`copit 0.6.0` to `(0, 6, 0)`, and anything unparsable to `()`."""
    digits = reported.rsplit(" ", 1)[-1].split(".")
    try:
        return tuple(int(part) for part in digits)
    except ValueError:
        return ()


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def install_all(project: Path, copit: str, components: dict[str, Any]) -> list[str]:
    """Set up a project and install every component into it."""
    (project / "pyproject.toml").write_text(PYPROJECT)

    for command in (
        [copit, "init"],
        [copit, "registry", "add", "chanx-kit", str(REPO_ROOT), "--to", TARGET],
    ):
        result = run(command, project)
        if result.returncode != 0:
            return [f"{' '.join(command)} failed: {result.stderr.strip()}"]

    problems: list[str] = []
    for name in sorted(components):
        variant_flags = [
            flag
            for variant in components[name].get("only_variants", [])
            for flag in ("--variant", variant)
        ]
        command = [copit, "add", f"@chanx-kit/{name}", "-y", "--no-packages"]
        result = run([*command, *variant_flags], project)
        if result.returncode != 0:
            problems.append(f"installing {name} failed: {result.stderr.strip()}")

    return problems


# copit copies the registry's licence alongside each component; not in the index.
LICENCE_STEMS = {"LICENSE", "LICENCE", "COPYING"}


def is_licence(relative: str) -> bool:
    name = Path(relative).name
    return name.split(".")[0].upper() in LICENCE_STEMS


def check_published_files(project: Path, index: dict[str, Any]) -> list[str]:
    """What landed on disk must be what the index publishes, plus licences."""
    problems: list[str] = []
    installed = project / TARGET
    marker = index.get("install", {}).get("package_marker")

    for name, component in index["components"].items():
        directory = installed / Path(component["path"]).name
        if not directory.is_dir():
            problems.append(
                f"{name}: not installed at {directory.relative_to(project)}"
            )
            continue

        on_disk = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and not is_licence(path.relative_to(directory).as_posix())
        }
        published = set(component["files"]) | ({marker} if marker else set())

        problems.extend(
            f"{name}: copied unpublished file {extra}"
            for extra in sorted(on_disk - published)
        )
        problems.extend(
            f"{name}: published file not copied: {missing}"
            for missing in sorted(published - on_disk)
        )

    return problems


def check_imports(project: Path, components: dict[str, Any]) -> list[str]:
    """The copied tree has to import."""
    imports = "; ".join(
        f"import app.ws_kits.{Path(component['path']).name}"
        for component in components.values()
    )
    result = run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, '.'); {imports}; print('ok')",
        ],
        project,
    )
    if result.returncode != 0:
        return [f"copied tree does not import: {result.stderr.strip()[-400:]}"]
    return []


def check_optional_group(project: Path, copit: str) -> list[str]:
    """Optional groups stay out of a normal install, and arrive when asked for.

    Also covers what the group *needs*: the copied tests import the chanx-testing
    harness, which the kit declares under its ``tests`` group rather than in
    ``requires``, so a user who never asks for tests must not receive it.
    """
    problems: list[str] = []
    presence = project / TARGET / "presence"
    harness = project / TARGET / "chanx_testing"

    if (presence / "tests").exists():
        problems.append("presence: tests were installed without --with tests")

    # Untrack both, so copit resolves the install afresh instead of treating them as
    # already present.
    run([copit, "remove", f"{TARGET}/presence", f"{TARGET}/chanx_testing"], project)
    shutil.rmtree(presence, ignore_errors=True)
    shutil.rmtree(harness, ignore_errors=True)

    result = run([copit, "add", "@chanx-kit/presence", "-y", "--no-packages"], project)
    if result.returncode != 0:
        problems.append(f"plain install failed: {result.stderr.strip()}")
    elif harness.exists():
        problems.append(
            "chanx-testing was installed by a kit whose tests were not requested"
        )

    run([copit, "remove", f"{TARGET}/presence"], project)
    shutil.rmtree(presence, ignore_errors=True)

    result = run(
        [copit, "add", "@chanx-kit/presence", "-y", "--no-packages", "--with", "tests"],
        project,
    )
    if result.returncode != 0:
        problems.append(f"--with tests failed: {result.stderr.strip()}")
        return problems

    if not (presence / "tests").is_dir():
        problems.append("presence: --with tests did not copy the tests")
    if not harness.is_dir():
        problems.append(
            "presence: --with tests did not pull in chanx-testing, so the copied "
            "tests import a harness that is not there"
        )

    return problems


def check_restricted_kits_are_refused(
    project: Path, copit: str, components: dict[str, Any]
) -> list[str]:
    """A kit limited to a variant must not install without it."""
    problems: list[str] = []
    for name, component in sorted(components.items()):
        required = component.get("only_variants")
        if not required:
            continue

        result = run(
            [copit, "add", f"@chanx-kit/{name}", "-y", "--no-packages"], project
        )
        if result.returncode == 0:
            problems.append(
                f"{name}: installed without --variant, but declares "
                f"only_variants {required}"
            )
        elif required[0] not in result.stderr:
            problems.append(
                f"{name}: refused without --variant, but the error does not name "
                f"{required[0]!r}: {result.stderr.strip()}"
            )

    return problems


def check(project: Path, copit: str) -> list[str]:
    index = json.loads(REGISTRY_JSON.read_text())
    components = index["components"]

    problems = install_all(project, copit, components)
    if not (project / TARGET).is_dir():
        return [*problems, f"nothing was installed into {TARGET}"]

    problems += check_published_files(project, index)
    problems += check_imports(project, components)
    problems += check_optional_group(project, copit)
    problems += check_restricted_kits_are_refused(project, copit, components)
    return problems


def main() -> int:
    minimum = ".".join(str(part) for part in MINIMUM_COPIT)
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").format(minimum=minimum)
    )
    parser.add_argument("--keep", action="store_true", help="keep the temp project")
    args = parser.parse_args()

    # COPIT wins over PATH: `uv run` prepends the venv's bin.
    copit = os.environ.get("COPIT") or shutil.which("copit")
    if copit is None or not Path(copit).exists():
        print(
            "copit was not found. Install it with `uv add --dev copit`, run it once with "
            "`uvx copit`, or set COPIT to a built binary.",
            file=sys.stderr,
        )
        return 1

    reported = copit_version(copit)
    if version_tuple(reported) < MINIMUM_COPIT:
        print(TOO_OLD_NOTE.format(minimum=minimum, version=reported), file=sys.stderr)
        return 1

    project = Path(tempfile.mkdtemp(prefix="chanx-kit-conformance-"))
    try:
        problems = check(project, copit)
    finally:
        if args.keep:
            print(f"Temp project kept at {project}")
        else:
            shutil.rmtree(project, ignore_errors=True)

    if problems:
        print(
            f"Install conformance failed ({len(problems)} problem(s)):", file=sys.stderr
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    count = len(json.loads(REGISTRY_JSON.read_text())["components"])
    print(f"Install conformance OK — {count} kits install and import.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
