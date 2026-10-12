from pathlib import Path

from quizz import paths

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_home_defaults_to_checkout_root(monkeypatch):
    monkeypatch.delenv("QUIZZ_HOME", raising=False)
    assert paths.home() == REPO_ROOT


def test_home_honours_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("QUIZZ_HOME", str(tmp_path))
    assert paths.home() == tmp_path
    assert paths.db_path() == tmp_path / "quizz.db"
    assert paths.build_dir() == tmp_path / "build"
    assert paths.library_dir() == tmp_path / "library"
