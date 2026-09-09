"""Runs all 4 strategies — BaselineFavouriteScalp plus the 3 research
candidates — against ONLY held_out_split.held_out_market_files(), using
each strategy's already-committed config/strategies.yaml parameters
unchanged (no re-tuning against this slice — that would defeat the
entire point of holding it out). Writes into the real data/runs.db via
the same paddock.sim.harness.run_simulation the CLI uses, so results are
readable the normal way (`paddock`'s /runs endpoints, sqlite directly).

Usage: `uv run python scripts/run_held_out_eval.py`, from engine/. Prints
each run_id as it completes — those are the run_ids
docs/strategy-research.md's held-out results table is computed from.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from held_out_split import held_out_market_files  # noqa: E402

from paddock.config.engine_config import load_engine_config  # noqa: E402
from paddock.config.settings import get_settings  # noqa: E402
from paddock.config.strategies_config import load_strategy_params  # noqa: E402
from paddock.sim.harness import run_simulation  # noqa: E402
from paddock.strategies.baseline import BaselineFavouriteScalp  # noqa: E402
from paddock.strategies.drift_following import DriftSteamFollower  # noqa: E402
from paddock.strategies.favourite_longshot_bias import FavouriteLongshotBias  # noqa: E402
from paddock.strategies.market_maker import LadderMarketMaker  # noqa: E402

STRATEGIES = [
    ("baseline", BaselineFavouriteScalp),
    ("drift_following", DriftSteamFollower),
    ("favourite_longshot_bias", FavouriteLongshotBias),
    ("market_maker", LadderMarketMaker),
]


def main() -> None:
    market_files = held_out_market_files()
    print(f"held-out slice: {len(market_files)} markets")

    settings = get_settings()
    engine_config = load_engine_config()

    for config_name, strategy_cls in STRATEGIES:
        strategy_kwargs = load_strategy_params(config_name)
        start = time.monotonic()
        run_id = run_simulation(
            strategy_cls,
            market_files,
            speed=0,
            commission_rate=engine_config.commission_rate,
            fill_model=engine_config.fill_model,
            data_dir=Path(settings.data_dir),
            strategy_kwargs=strategy_kwargs,
        )
        elapsed = time.monotonic() - start
        print(f"{config_name}: run_id={run_id} ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
