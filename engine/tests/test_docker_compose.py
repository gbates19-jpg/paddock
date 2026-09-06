"""Structural checks on the repo-root docker-compose.yml + Dockerfiles.

Step 5's Docker support is UNTESTED against a real daemon — this Mac has
none installed (see README.md "Docker" and docs/phase1.md) — so this can
only catch config-shape regressions (a typo'd key, a dropped port/volume),
not "does it actually build and run". If `docker` is on PATH, we also ask
it to validate the compose file for real; everywhere else that check is
skipped rather than silently passing.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text())


def test_engine_and_ui_dockerfiles_exist():
    assert (REPO_ROOT / "engine" / "Dockerfile").is_file()
    assert (REPO_ROOT / "ui" / "Dockerfile").is_file()


def test_compose_defines_engine_and_ui_services(compose):
    assert set(compose["services"]) == {"engine", "ui"}


def test_engine_service_builds_local_dockerfile_and_exposes_api_port(compose):
    engine = compose["services"]["engine"]
    assert engine["build"] == "./engine"
    assert "8000:8000" in engine["ports"]


def test_ui_service_builds_local_dockerfile_and_exposes_dev_port(compose):
    ui = compose["services"]["ui"]
    assert ui["build"] == "./ui"
    assert "5173:5173" in ui["ports"]


def test_engine_data_dir_is_bind_mounted_and_overridden_for_container(compose):
    """Matches paddock.config.settings._DEFAULT_DATA_DIR's comment: the
    <repo_root>/data default is a local-dev-only fallback — inside a
    container it must be pointed at the bind mount explicitly."""
    engine = compose["services"]["engine"]
    assert "./data:/data" in engine["volumes"]
    assert engine["environment"]["PADDOCK_DATA_DIR"] == "/data"


def test_both_services_load_their_gitignored_env_file(compose):
    assert compose["services"]["engine"]["env_file"] == ["./engine/.env"]
    assert compose["services"]["ui"]["env_file"] == ["./ui/.env"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker isn't installed on this machine")
def test_docker_compose_config_is_valid():
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
