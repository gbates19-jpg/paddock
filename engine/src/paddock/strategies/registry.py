"""Name -> strategy class lookup for the `paddock sim run --strategy` CLI flag.

`baseline` (BaselineFavouriteScalp) lands in step 3.
"""
from __future__ import annotations

from flumine.strategy.strategy import BaseStrategy

from paddock.strategies.passive import PassiveObserver

REGISTRY: dict[str, type[BaseStrategy]] = {
    "passive": PassiveObserver,
}


def get_strategy_class(name: str) -> type[BaseStrategy]:
    try:
        return REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(REGISTRY)) or "(none registered)"
        raise ValueError(f"Unknown strategy {name!r}. Available: {available}") from None
