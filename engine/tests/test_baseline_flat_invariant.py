"""BaselineFavouriteScalp must hold zero net position on the favourite
runner by market close, in every reachable scenario. Driven through real
flumine order lifecycle (real Trade/Order/SimulatedOrder, real
LtpCrossMiddleware matching) against a synthetic market file with an
exact, hand-picked ltp sequence — a real historic file doesn't give us
that control, and the invariant needs to be checked against actual order
matching, not a hand-simulated stand-in for it.

All ltp values used are real Betfair tick-ladder prices — the increment
changes at 10.0 (0.2 below, 0.5 at/above), so e.g. 10.2/10.3/10.4 are
*invalid* prices flumine's own ORDER_VALIDATION control rejects. Found
this the hard way while writing this file: an early draft of scenario 3
used 10.2-10.4 and the closer order silently violated with "Order price
is not valid for CLASSIC ladder" — worth remembering for any future test
that fabricates prices near a tick-size boundary.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from flumine import FlumineSimulation
from flumine.streams.betfairhistoricalstream import BetfairHistoricalStream

from paddock.sim.clients import build_replay_client
from paddock.sim.fill_models import LtpCrossMiddleware
from paddock.strategies.baseline import BaselineFavouriteScalp
from synthetic_market import write_synthetic_market


def _net_position(orders) -> float:
    back = sum(o.size_matched for o in orders if o.side == "BACK")
    lay = sum(o.size_matched for o in orders if o.side == "LAY")
    return round(back - lay, 2)


def _run(tmp_path: Path, market_id: str, selection_id: int, ltp_ticks, winner: bool):
    market_file = tmp_path / f"{market_id}.jsonl"
    write_synthetic_market(market_file, market_id, selection_id, ltp_ticks, winner)

    client = build_replay_client(0.02)
    framework = FlumineSimulation(client=client)
    strategy = BaselineFavouriteScalp(
        streams=[BetfairHistoricalStream(file_path=str(market_file))],
        max_order_exposure=100,
        max_selection_exposure=100,
    )
    framework.add_strategy(strategy)
    framework.add_market_middleware(LtpCrossMiddleware())
    framework.run()

    markets = list(framework.markets)
    assert len(markets) == 1
    return list(markets[0].blotter)


def test_entry_never_matched_stays_flat_and_places_no_exit(tmp_path):
    # ltp only ever drifts down from the entry price (10.0) — BACK never
    # crosses (needs ltp >= 10.0 again), so entry is cancelled unmatched
    # at the T-30s cutoff and no exit is ever placed.
    orders = _run(
        tmp_path,
        "1.900001",
        5000001,
        [(290, 10.0), (280, 9.0), (200, 8.0), (100, 7.0), (40, 6.0), (25, 5.5)],
        winner=False,
    )

    assert len(orders) == 1
    assert orders[0].side == "BACK"
    assert orders[0].size_matched == 0.0
    assert _net_position(orders) == 0.0


def test_entry_and_exit_both_fully_match(tmp_path):
    # ltp rises to cross the entry (BACK matches @10.0), then drops enough
    # to cross the exit (LAY @9.6, 2 ticks below) well before the cutoff.
    orders = _run(
        tmp_path,
        "1.900002",
        5000002,
        [(290, 10.0), (280, 10.5), (200, 9.0), (100, 8.0), (40, 7.0), (25, 6.5)],
        winner=True,
    )

    assert len(orders) == 2
    entry = next(o for o in orders if o.notes.get("role") == "entry")
    exit_ = next(o for o in orders if o.notes.get("role") == "exit")
    assert entry.size_matched == 2.0
    assert exit_.size_matched == 2.0
    assert exit_.order_type.price < entry.order_type.price
    assert _net_position(orders) == 0.0


def test_exit_unmatched_at_cutoff_gets_force_closed(tmp_path):
    # ltp crosses to match entry, then holds flat above the exit price
    # (9.6) all the way to the cutoff — exit never crosses. At T-30s the
    # exit is cancelled and a closer order (accept the red) is placed at
    # the current price, which crosses immediately since ltp hasn't moved.
    orders = _run(
        tmp_path,
        "1.900003",
        5000003,
        [
            (290, 10.0),
            (280, 10.5),
            (200, 10.5),
            (100, 10.5),
            (40, 10.5),
            (25, 10.5),
            (20, 10.5),
            (10, 10.5),
        ],
        winner=True,
    )

    assert len(orders) == 3
    entry = next(o for o in orders if o.notes.get("role") == "entry")
    exit_ = next(o for o in orders if o.notes.get("role") == "exit")
    closer = next(o for o in orders if o.notes.get("role") == "closer")
    assert entry.size_matched == 2.0
    assert exit_.size_matched == 0.0  # never crossed
    assert closer.size_matched == 2.0  # force-closed the full shortfall
    assert _net_position(orders) == 0.0


@pytest.mark.parametrize(
    "ltp_ticks,winner",
    [
        ([(290, 10.0), (280, 9.0), (200, 8.0), (100, 7.0), (40, 6.0), (25, 5.5)], False),
        ([(290, 10.0), (280, 10.5), (200, 9.0), (100, 8.0), (40, 7.0), (25, 6.5)], True),
        (
            [
                (290, 10.0),
                (280, 10.5),
                (200, 10.5),
                (100, 10.5),
                (40, 10.5),
                (25, 10.5),
                (20, 10.5),
                (10, 10.5),
            ],
            True,
        ),
    ],
)
def test_flat_at_close_across_all_scenarios(tmp_path, ltp_ticks, winner):
    orders = _run(tmp_path, "1.900099", 5000099, ltp_ticks, winner)
    assert _net_position(orders) == 0.0
