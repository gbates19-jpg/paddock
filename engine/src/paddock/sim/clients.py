"""Client construction for each mode.

Safety-load-bearing: flumine's Clients.simulated property (flumine 3.2.0,
flumine/clients/clients.py) picks flumine.simulated_execution — which never
calls the real betting endpoint — whenever `client.VENUE == VenueType.SIMULATED
or client.paper_trade` is true. build_replay_client and build_paper_client
both produce clients that satisfy that condition; see
tests/test_safety.py::test_replay_and_paper_clients_never_reach_real_execution
for a structural check of this that doesn't depend on any strategy existing.
"""
from __future__ import annotations

import betfairlightweight
from flumine.clients import BetfairClient, SimulatedClient


def build_replay_client(commission_rate: float) -> SimulatedClient:
    return SimulatedClient(commission_base=commission_rate)


def build_paper_client(
    trading: betfairlightweight.APIClient, commission_rate: float
) -> BetfairClient:
    return BetfairClient(trading, paper_trade=True, commission_base=commission_rate)
