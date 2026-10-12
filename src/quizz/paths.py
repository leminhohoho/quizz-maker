"""Locations of local data (`$QUIZZ_HOME`)."""

import os
from pathlib import Path

# src/quizz/paths.py -> checkout root (holds pyproject.toml) for an editable install.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]


def home() -> Path:
    override = os.environ.get("QUIZZ_HOME")
    if override:
        return Path(override)
    return _CHECKOUT_ROOT


def db_path() -> Path:
    return home() / "quizz.db"


def build_dir() -> Path:
    return home() / "build"


def library_dir() -> Path:
    return home() / "library"
