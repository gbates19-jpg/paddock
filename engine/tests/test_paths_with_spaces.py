"""The repo itself lives under `/Volumes/Mac Mini 2TB/...` — a path with a
space. Anything that builds paths via string concatenation or shells out
without list-args/quoting breaks there. This exercises the CLI and market
file discovery from inside a directory whose name contains a space.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from click.testing import CliRunner

from paddock.cli import main
from paddock.sim.harness import discover_market_files

SAMPLE_MARKET = Path(__file__).parent / "resources" / "1.170258213"


def test_discover_market_files_under_a_path_with_a_space(tmp_path):
    spaced_dir = tmp_path / "data dir with spaces" / "2026" / "07"
    spaced_dir.mkdir(parents=True)
    dest = spaced_dir / SAMPLE_MARKET.name
    shutil.copyfile(SAMPLE_MARKET, dest)

    found = discover_market_files(tmp_path / "data dir with spaces")

    assert found == [dest]


def test_sim_run_cli_from_a_path_with_a_space(tmp_path, monkeypatch):
    spaced_root = tmp_path / "Paddock Test Dir"
    data_dir = spaced_root / "data"
    market_dir = data_dir / "2026" / "07"
    market_dir.mkdir(parents=True)
    shutil.copyfile(SAMPLE_MARKET, market_dir / SAMPLE_MARKET.name)

    monkeypatch.setenv("PADDOCK_DATA_DIR", str(data_dir))

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["sim", "run", "--strategy", "passive", "--data", str(market_dir), "--speed", "0"],
    )

    assert result.exit_code == 0, result.output
    assert "Run" in result.output
    assert (data_dir / "runs.db").exists()
