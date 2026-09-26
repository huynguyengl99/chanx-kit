"""Templates' copied kits must match kits/. Refresh with `copit add` in the template."""

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = sorted(p.parent for p in (REPO_ROOT / "templates").glob("*/copit.toml"))
INDEX: dict[str, Any] = json.loads((REPO_ROOT / "copit-registry.json").read_text())


def installed_components(template: Path) -> list[tuple[str, dict[str, Any]]]:
    config = tomllib.loads((template / "copit.toml").read_text())
    return [
        (source["component"].split(":", 1)[1], source)
        for source in config.get("sources", [])
        if source.get("component", "").startswith("chanx-kit:")
    ]


def test_there_is_a_template() -> None:
    assert TEMPLATES, "no templates/*/copit.toml found"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_the_registry_is_pinned_to_a_release(template: Path) -> None:
    config = tomllib.loads((template / "copit.toml").read_text())
    source = config["registries"]["chanx-kit"]["source"]

    assert source.startswith("github:huynguyengl99/chanx-kit@v"), (
        f"{template.name}: the registry should be pinned to a release tag, got {source}"
    )


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_copied_kits_match_the_current_kits(template: Path) -> None:
    components = installed_components(template)
    assert components, f"{template.name}: no chanx-kit components in copit.toml"

    for name, source in components:
        published = INDEX["components"][name]
        assert source["component_version"] == published["version"], (
            f"{template.name}: {name} is {source['component_version']}, "
            f"the registry publishes {published['version']}"
        )

        copied = template / source["path"]
        kit = REPO_ROOT / published["path"]
        for file in published["files"]:
            assert (copied / file).read_text() == (kit / file).read_text(), (
                f"{template.name}: {source['path']}/{file} differs from {kit}/{file}"
            )
