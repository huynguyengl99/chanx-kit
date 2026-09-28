import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import recipes  # noqa: E402


def test_recipes_and_documented_commands_are_installable() -> None:
    assert recipes.check() == []


def test_an_unknown_kit_is_a_problem() -> None:
    assert recipes.command_problems("@chanx-kit/nope @chanx-kit-ui/nada") == [
        "no server kit 'nope'",
        "no UI kit 'nada'",
    ]


def test_a_part_no_requested_kit_has_is_a_problem() -> None:
    assert recipes.command_problems("@chanx-kit/notification --only stt") == [
        "no requested kit has a part 'stt'"
    ]


def test_a_placeholder_part_is_not_checked() -> None:
    assert recipes.command_problems("@chanx-kit/deepgram --only <part>") == []


def test_a_ui_kit_needs_its_contract_from_the_parts_kept() -> None:
    problems = recipes.recipe_problems(
        {"add": "@chanx-kit/deepgram @chanx-kit-ui/transcriber --only tts"}
    )

    assert problems == [
        "transcriber needs transcriber@1, which no server kit here provides"
    ]


def test_a_composite_ui_kit_needs_every_contract_it_brings() -> None:
    problems = recipes.recipe_problems(
        {"add": "@chanx-kit/notification @chanx-kit-ui/voice-agent"}
    )

    assert [p.split(",")[0] for p in problems] == [
        "voice-agent needs ag-ui@1",
        "voice-agent needs synthesizer@1",
        "voice-agent needs transcriber@1",
    ]


def test_each_listed_provider_is_checked_in_place_of_the_last_server_kit() -> None:
    problems = recipes.recipe_problems(
        {
            "add": "@chanx-kit/deepgram @chanx-kit-ui/transcriber --only stt",
            "providers": ["openai", "nope"],
        }
    )

    assert problems == [
        "with nope: no server kit 'nope'",
        "with nope: no requested kit has a part 'stt'",
    ]
