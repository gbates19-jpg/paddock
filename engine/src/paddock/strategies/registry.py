"""Name -> strategy class lookup for the `paddock sim run --strategy` CLI flag."""
from __future__ import annotations

from flumine.strategy.strategy import BaseStrategy

from paddock.strategies.baseline import BaselineFavouriteScalp
from paddock.strategies.drift_following import DriftSteamFollower
from paddock.strategies.favourite_longshot_bias import FavouriteLongshotBias
from paddock.strategies.market_maker import LadderMarketMaker
from paddock.strategies.passive import PassiveObserver

REGISTRY: dict[str, type[BaseStrategy]] = {
    "passive": PassiveObserver,
    "baseline": BaselineFavouriteScalp,
    "drift_following": DriftSteamFollower,
    "favourite_longshot_bias": FavouriteLongshotBias,
    "market_maker": LadderMarketMaker,
}


def get_strategy_class(name: str) -> type[BaseStrategy]:
    try:
        return REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(REGISTRY)) or "(none registered)"
        raise ValueError(f"Unknown strategy {name!r}. Available: {available}") from None
