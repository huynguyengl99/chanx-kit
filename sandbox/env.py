"""The git-ignored ``.env`` at the repo root; variables already set win."""

from pathlib import Path

from dotenv import load_dotenv


def load_env() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
