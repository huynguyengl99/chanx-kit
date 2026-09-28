"""Tests for the registry tooling itself.

The rules encoded here are the ones that keep a community registry honest: a core
component must never depend on contrib, dependencies must exist, and the graph must
stay acyclic.
"""

import json
import pathlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import registry as registry_module  # noqa: E402


def make_registry(components: dict[str, dict[str, Any]]) -> registry_module.Registry:
    filled = {
        name: {"requires": [], "tier": "core", "only_variants": [], **component}
        for name, component in components.items()
    }
    return registry_module.Registry(
        config={"tier_rules": {"core": ["core"], "contrib": ["core", "contrib"]}},
        components=filled,
    )


def test_core_may_not_depend_on_contrib() -> None:
    registry = make_registry(
        {
            "helper": {"tier": "contrib"},
            "widget": {"tier": "core", "requires": ["helper"]},
        }
    )

    problems = [str(p) for p in registry_module.validate_graph(registry)]

    assert any("cannot depend on" in p for p in problems)


def test_a_group_requirement_obeys_the_tier_rule() -> None:
    """An optional group is a way to install less, not a way around the tier rule."""
    registry = make_registry(
        {
            "helper": {"tier": "contrib"},
            "widget": {
                "tier": "core",
                "optional": {"tests": {"requires": ["helper"]}},
            },
        }
    )

    problems = [str(p) for p in registry_module.validate_graph(registry)]

    assert any("cannot depend on" in p and "'tests' group" in p for p in problems)


def test_a_group_requirement_must_name_a_known_component() -> None:
    registry = make_registry(
        {"widget": {"optional": {"tests": {"requires": ["ghost"]}}}}
    )

    problems = [str(p) for p in registry_module.validate_graph(registry)]

    assert any("unknown component 'ghost'" in p for p in problems)


def test_a_cycle_through_a_group_requirement_is_reported() -> None:
    registry = make_registry(
        {
            "a": {"optional": {"tests": {"requires": ["b"]}}},
            "b": {"requires": ["a"]},
        }
    )

    problems = [str(p) for p in registry_module.validate_graph(registry)]

    assert any("dependency cycle" in p for p in problems)


def test_contrib_may_depend_on_core() -> None:
    registry = make_registry(
        {
            "widget": {"tier": "core"},
            "helper": {"tier": "contrib", "requires": ["widget"]},
        }
    )

    assert registry_module.validate_graph(registry) == []


def test_unknown_dependency_is_reported() -> None:
    registry = make_registry({"widget": {"requires": ["ghost"]}})

    problems = [str(p) for p in registry_module.validate_graph(registry)]

    assert any("unknown component 'ghost'" in p for p in problems)


def test_dependency_cycle_is_reported() -> None:
    registry = make_registry(
        {
            "a": {"requires": ["b"]},
            "b": {"requires": ["a"]},
        }
    )

    problems = [str(p) for p in registry_module.find_cycles(registry)]

    assert any("dependency cycle" in p for p in problems)


def test_self_dependency_is_reported() -> None:
    registry = make_registry({"a": {"requires": ["a"]}})

    assert registry_module.find_cycles(registry)


def test_deep_chain_without_a_cycle_is_accepted() -> None:
    registry = make_registry(
        {
            "a": {"requires": ["b"]},
            "b": {"requires": ["c"]},
            "c": {},
        }
    )

    assert registry_module.find_cycles(registry) == []


def test_the_real_registry_is_valid() -> None:
    _, problems = registry_module.build()

    assert [str(p) for p in problems] == []


def test_registry_json_is_committed_and_current() -> None:
    registry, _ = registry_module.build()

    generated = registry_module.serialise(registry)
    committed = registry_module.SERVER.index.read_text()

    assert committed == generated, (
        "copit-registry.json is stale — run: python scripts/registry.py build"
    )


def test_every_component_declares_chanx() -> None:
    """A copied kit must be installable into a project that has nothing yet."""
    registry, _ = registry_module.build()

    for name, component in registry.components.items():
        assert any(
            dependency.startswith("chanx") for dependency in component["dependencies"]
        ), f"{name} should depend on chanx"


@pytest.mark.parametrize("required", ["__init__.py", "README.md"])
def test_every_component_ships_required_files(required: str) -> None:
    registry, _ = registry_module.build()

    for name, component in registry.components.items():
        assert required in component["files"], f"{name} is missing {required}"


def test_tests_are_not_shipped_to_users() -> None:
    registry, _ = registry_module.build()

    for name, component in registry.components.items():
        assert not any(f.startswith("tests/") for f in component["files"]), (
            f"{name} would copy its tests into user projects"
        )


def test_registry_json_parses_as_the_documented_shape() -> None:
    document = json.loads(registry_module.SERVER.index.read_text())

    assert document["version"] == registry_module.SCHEMA_VERSION
    assert document["ecosystem"] == "python"
    assert set(document["components"]) == {
        "ag-ui",
        "audio-stream-in",
        "audio-stream-out",
        "chanx-testing",
        "conversation-store",
        "deepgram",
        "django-message-store",
        "elevenlabs",
        "fake-voice",
        "media-stream-in",
        "media-stream-out",
        "notification",
        "openai",
        "pipecat-bridge",
        "presence",
        "pydantic-ai-ag-ui",
        "redis-presence-store",
        "room-chat",
        "voice-agent",
    }
    assert document["components"]["pydantic-ai-ag-ui"]["requires"] == [
        "ag-ui",
        "conversation-store",
    ]
    assert document["components"]["redis-presence-store"]["requires"] == ["presence"]
    assert document["components"]["room-chat"]["requires"] == ["presence"]
    # Published so copit can refuse the install; without it the kit's models would land
    # in a project with no Django to load them.
    assert document["components"]["django-message-store"]["only_variants"] == ["django"]


def test_generated_index_matches_copits_schema() -> None:
    registry, _ = registry_module.build()

    document = json.loads(registry_module.serialise(registry))

    assert registry_module.schema_problems(document) == []


Mutation = Callable[[dict[str, Any]], object]

# Annotated as a named list so the lambda parameters are inferred; pyright cannot infer
# them through the parametrize decorator.
MALFORMED: list[tuple[Mutation, str]] = [
    (lambda document: document.pop("version"), "version"),
    (lambda document: document.update(version="one"), "version"),
    (lambda document: document.pop("components"), "components"),
    (lambda document: document.update(surprise=True), "surprise"),
    (lambda document: document["components"]["presence"].pop("path"), "path"),
    (
        lambda document: document["components"]["presence"].update(requires="presence"),
        "requires",
    ),
    (
        lambda document: document["components"]["presence"].update(files="one.py"),
        "files",
    ),
]


@pytest.mark.parametrize(("mutate", "expected"), MALFORMED)
def test_schema_rejects_a_malformed_index(mutate: Mutation, expected: str) -> None:
    """The schema is the contract copit validates on fetch; catch breaks at the producer."""
    registry, _ = registry_module.build()
    document = json.loads(registry_module.serialise(registry))

    mutate(document)
    problems = [str(problem) for problem in registry_module.schema_problems(document)]

    assert problems, f"schema accepted a document missing/!invalid {expected}"
    assert any(expected in problem for problem in problems), problems


def test_optional_groups_are_published_but_not_installed_by_default() -> None:
    registry, _ = registry_module.build()

    presence = registry.components["presence"]

    assert not any(f.startswith("tests/") for f in presence["files"])
    assert presence["optional"]["tests"], (
        "tests should be published as an optional group"
    )


def test_the_harness_is_pulled_in_by_the_tests_group_not_the_kit() -> None:
    """A user who installs a kit without its tests must not get the harness."""
    registry, _ = registry_module.build()

    for name in ("ag-ui", "notification", "presence", "room-chat"):
        component = registry.components[name]
        assert "chanx-testing" not in component["requires"], (
            f"{name} would copy the harness into projects that never asked for tests"
        )
        assert component["optional"]["tests"]["requires"] == ["chanx-testing"]


def test_a_group_without_requirements_stays_a_bare_file_list() -> None:
    """The short form is still what the index publishes when there is nothing to add."""
    registry, _ = registry_module.build()

    assert isinstance(registry.components["chanx-testing"]["optional"]["tests"], list)


def test_every_kit_exposes_a_topic() -> None:
    """A kit is a topic: a pattern, its own handlers, its own group."""
    import importlib

    from chanx.core.topic import Topic

    for name, component in registry_module.build()[0].components.items():
        package = pathlib.Path(component["path"]).name
        try:
            module = importlib.import_module(f"kits.{package}.topics")
        except ModuleNotFoundError:
            continue

        topics = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type)
            and issubclass(obj, Topic)
            and obj is not Topic
            and obj.__module__ == module.__name__
        ]
        assert topics, f"{name}: kits/{package}/topics.py declares no Topic"

        for topic in topics:
            if "pattern" not in topic.__dict__:
                continue  # a shared base, parametrised by its subclasses
            sample = topic.pattern.format(**dict.fromkeys(topic.param_names, "x"))
            # a parameterless topic matches with no params, which is {} not None
            assert topic.parse(sample) is not None, (
                f"{name}: {topic.__name__} cannot parse its own pattern"
            )


def test_the_ui_registry_is_valid_and_current() -> None:
    registry, problems = registry_module.build(registry_module.UI)

    assert [str(p) for p in problems] == []
    assert registry_module.UI.index.read_text() == registry_module.serialise(
        registry
    ), "ui/copit-registry.json is stale — run: python scripts/registry.py build"


def test_every_contract_reference_resolves() -> None:
    server, _ = registry_module.build(registry_module.SERVER)
    ui, _ = registry_module.build(registry_module.UI)

    assert registry_module.contract_problems(server, ui) == []


def test_a_stale_contract_version_names_the_current_one() -> None:
    server, _ = registry_module.build(registry_module.SERVER)
    ui = registry_module.Registry(
        config={}, contracts={"feed": {"consumes": ["notification@0"]}}
    )

    problems = [str(p) for p in registry_module.contract_problems(server, ui)]

    assert problems == [
        "feed: consumes 'notification@0', which no kit defines; "
        "the current version is notification@1"
    ]


def test_contracts_stay_out_of_the_published_indexes() -> None:
    for layout in registry_module.LAYOUTS:
        document = json.loads(layout.index.read_text())
        for component in document["components"].values():
            assert not {"defines", "implements", "consumes", "contract_topic"} & set(
                component
            )


def test_only_react_variant_files_import_react() -> None:
    """A UI kit installed without the react variant must still compile."""
    registry, _ = registry_module.build(registry_module.UI)

    for name, component in registry.components.items():
        react_files = set(component["variants"].get("react", {}).get("include", []))
        for file in set(component["files"]) - react_files:
            if not file.endswith((".ts", ".tsx")):
                continue
            source = (REPO_ROOT / component["path"] / file).read_text()
            assert "from 'react'" not in source and "/react'" not in source, (
                f"{name}/{file} imports React outside the react variant"
            )


def test_provider_kits_publish_their_parts_subtractively() -> None:
    """copit before 0.9 ignores parts and installs the whole kit, so the kit itself must
    carry everything its parts need."""
    registry, _ = registry_module.build()

    for name in ("deepgram", "elevenlabs", "openai", "fake-voice"):
        component = registry.components[name]
        parts = component["parts"]
        assert set(parts) == {"stt", "tts"}, name
        assert "transcriber.py" in parts["stt"]["include"], name
        assert "synthesizer.py" in parts["tts"]["include"], name
        for part in parts.values():
            assert set(part.get("requires", [])) <= set(component["requires"]), name
            assert set(part.get("dependencies", [])) <= set(
                component["dependencies"]
            ), name
            assert set(part["include"]) <= {
                *component["files"],
                *component["optional"]["tests"]["include"],
            }, name


def test_a_part_listing_what_its_kit_lacks_is_a_problem() -> None:
    data = {
        "requires": ["a"],
        "parts": {"x": {"include": ["x.py"], "requires": ["a", "b"]}},
    }

    _, problems = registry_module.build_parts("kit", data, ["x.py"], {})

    assert [str(p) for p in problems] == [
        "kit: part 'x' lists requires ['b'] the kit does not; "
        "a copit without parts would install the kit without them"
    ]


@pytest.mark.parametrize(
    ("data", "problems"),
    [
        ({"role": "feature", "area": "voice"}, []),
        ({"role": "provider", "implements": ["transcriber@1"]}, []),
        ({"area": "voice"}, ["role must be one of"]),
        ({"role": "feature"}, ["area must be one of"]),
        ({"role": "provider"}, ["a provider implements no contract"]),
        (
            {"role": "provider", "implements": ["x@1"], "area": "voice"},
            ["a provider has no area"],
        ),
    ],
)
def test_every_kit_is_filed_for_the_docs(
    data: dict[str, Any], problems: list[str]
) -> None:
    found = registry_module.catalog_problems(data)

    assert len(found) == len(problems)
    assert all(f.startswith(p) for f, p in zip(found, problems, strict=True))
