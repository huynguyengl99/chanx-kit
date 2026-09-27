"""UI kits installed through copit must match ui/. Refresh with `copit update-all`."""

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX: dict[str, Any] = json.loads(
    (REPO_ROOT / "ui" / "copit-registry.json").read_text()
)
PROJECTS = sorted(
    path.parent
    for path in [
        REPO_ROOT / "sandbox" / "ui" / "copit.toml",
        *REPO_ROOT.glob("templates/*/copit.toml"),
    ]
    if "chanx-kit-ui" in tomllib.loads(path.read_text()).get("registries", {})
)


def installed(project: Path) -> list[tuple[str, dict[str, Any]]]:
    config = tomllib.loads((project / "copit.toml").read_text())
    return [
        (source["component"].split(":", 1)[1], source)
        for source in config.get("sources", [])
        if source.get("component", "").startswith("chanx-kit-ui:")
    ]


def test_the_sandbox_installs_every_ui_kit() -> None:
    names = {name for name, _ in installed(REPO_ROOT / "sandbox" / "ui")}
    assert names == set(INDEX["components"])


@pytest.mark.parametrize(
    "project", PROJECTS, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_copied_ui_kits_match_ui(project: Path) -> None:
    for name, source in installed(project):
        published = INDEX["components"][name]
        assert source["component_version"] == published["version"], name
        assert "react" in source.get("variants", []), f"{name} lacks its React files"

        for file in published["files"]:
            copied = project / source["path"] / file
            assert (
                copied.read_text() == (REPO_ROOT / published["path"] / file).read_text()
            ), f"{copied} differs from ui/{name}/{file}"
