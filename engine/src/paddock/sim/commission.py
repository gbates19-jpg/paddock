"""Commission math — must exactly mirror flumine's Market.cleared():

    commission = round(max(profit * client.commission_base, 0), 2)

(confirmed in flumine 3.2.0 flumine/markets/market.py). Both the
SimulatedClient/BetfairClient we construct AND the pnl worker use this same
function against the same engine_config.commission_rate, so the two never
drift — see tests/test_commission.py for the equality check against
flumine's own market.cleared(client) output.
"""
from __future__ import annotations


def compute_commission(profit: float, commission_rate: float) -> float:
    return round(max(profit * commission_rate, 0.0), 2)
