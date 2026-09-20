"""Tests for the external application-data root (OPEN_NOTEBOOK_DATA_DIR).

Covers Milestone 3 storage externalization:
- default behavior without the variable (historical ./data),
- redirection of all derived paths when set,
- restart persistence against the same root,
- isolation (no ./data writes when external),
- blank/trailing-separator handling and TIKTOKEN_CACHE_DIR precedence.
"""

import importlib
import os
from pathlib import Path

import pytest

import open_notebook.config as config

_MANAGED_VARS = ("OPEN_NOTEBOOK_DATA_DIR", "TIKTOKEN_CACHE_DIR")


@pytest.fixture()
def config_env(tmp_path, monkeypatch):
    """Reload open_notebook.config with a controlled environment.

    Runs with cwd rooted at tmp_path. Returns a helper that applies env
    overrides (all managed vars cleared first) and reloads the module.
    Original environment and module state are restored afterwards.
    """
    monkeypatch.chdir(tmp_path)
    saved = {var: os.environ.get(var) for var in _MANAGED_VARS}

    def apply(**overrides):
        for var in _MANAGED_VARS:
            os.environ.pop(var, None)
        for key, value in overrides.items():
            os.environ[key] = value
        return importlib.reload(config)

    try:
        yield apply
    finally:
        for var in _MANAGED_VARS:
            os.environ.pop(var, None)
        for var, value in saved.items():
            if value is not None:
                os.environ[var] = value
        importlib.reload(config)


def test_default_uses_repo_relative_data(config_env, tmp_path):
    cfg = config_env()
    assert cfg.DATA_FOLDER == "./data"
    assert cfg.UPLOADS_FOLDER == "./data/uploads"
    assert cfg.PODCASTS_FOLDER == "./data/podcasts"
    assert cfg.LANGGRAPH_CHECKPOINT_FILE == "./data/sqlite-db/checkpoints.sqlite"
    assert cfg.TIKTOKEN_CACHE_DIR == "./data/tiktoken-cache"
    for sub in ("uploads", "podcasts", "sqlite-db", "tiktoken-cache"):
        assert (tmp_path / "data" / sub).is_dir()


def test_external_root_redirects_all_paths(config_env, tmp_path):
    root = tmp_path / "external"
    cfg = config_env(OPEN_NOTEBOOK_DATA_DIR=str(root))
    assert cfg.DATA_FOLDER == str(root)
    assert cfg.UPLOADS_FOLDER == f"{root}/uploads"
    assert cfg.PODCASTS_FOLDER == f"{root}/podcasts"
    assert cfg.LANGGRAPH_CHECKPOINT_FILE == f"{root}/sqlite-db/checkpoints.sqlite"
    assert cfg.TIKTOKEN_CACHE_DIR == f"{root}/tiktoken-cache"
    for sub in ("uploads", "podcasts", "sqlite-db", "tiktoken-cache"):
        assert (root / sub).is_dir()


def test_blank_value_falls_back_to_default(config_env):
    assert config_env(OPEN_NOTEBOOK_DATA_DIR="   ").DATA_FOLDER == "./data"


def test_trailing_separators_stripped(config_env):
    cfg = config_env(OPEN_NOTEBOOK_DATA_DIR="C:\\extdata\\")
    assert cfg.DATA_FOLDER == "C:\\extdata"
    assert cfg.UPLOADS_FOLDER == "C:\\extdata/uploads"


def test_explicit_tiktoken_cache_wins(config_env, tmp_path):
    root = tmp_path / "external"
    cache = tmp_path / "cache"
    cfg = config_env(
        OPEN_NOTEBOOK_DATA_DIR=str(root), TIKTOKEN_CACHE_DIR=str(cache)
    )
    assert cfg.TIKTOKEN_CACHE_DIR == str(cache)
    assert cache.is_dir()
    assert cfg.UPLOADS_FOLDER == f"{root}/uploads"


def test_restart_against_same_root_preserves_data(config_env, tmp_path):
    root = tmp_path / "external"
    cfg = config_env(OPEN_NOTEBOOK_DATA_DIR=str(root))
    marker = Path(cfg.UPLOADS_FOLDER) / "marker.bin"
    marker.write_bytes(b"keep")
    cfg2 = config_env(OPEN_NOTEBOOK_DATA_DIR=str(root))
    assert cfg2.UPLOADS_FOLDER == cfg.UPLOADS_FOLDER
    assert cfg2.LANGGRAPH_CHECKPOINT_FILE == cfg.LANGGRAPH_CHECKPOINT_FILE
    assert marker.read_bytes() == b"keep"


def test_no_repo_data_written_when_external(config_env, tmp_path):
    config_env(OPEN_NOTEBOOK_DATA_DIR=str(tmp_path / "external"))
    assert not (tmp_path / "data").exists()
