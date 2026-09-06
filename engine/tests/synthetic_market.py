"""Builds a minimal, fully-controlled JSONL market-change stream so
BaselineFavouriteScalp's flat-at-off invariant can be tested against real
flumine order lifecycle (real Trade/Order/SimulatedOrder machinery, real
LtpCrossMiddleware matching) rather than a hand-rolled simulation of it —
with exact control over the ltp sequence, which a real historic file
doesn't give us.

Required MarketDefinition fields confirmed against betfairlightweight's
resource __init__ (streamingresources.py) — omitting any of these raises
a TypeError at parse time, not a soft failure.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _line(pt_ms: int, market_id: str, mc_extra: dict) -> str:
    return json.dumps({"op": "mcm", "pt": pt_ms, "mc": [{"id": market_id, **mc_extra}]})


def build_synthetic_market(
    market_id: str,
    selection_id: int,
    off_dt: datetime,
    ltp_ticks: list[tuple[float, float]],
    winner: bool = True,
) -> str:
    """ltp_ticks: [(seconds_before_off, ltp), ...] in the order they occur
    (may include negative seconds_before_off for post-off ticks, needed so
    a T-30s closer order gets a chance to match before the market shuts)."""
    off_epoch_ms = int(off_dt.timestamp() * 1000)

    base_definition = {
        "betDelay": 0,
        "bettingType": "ODDS",
        "bspMarket": False,
        "bspReconciled": False,
        "complete": True,
        "crossMatching": False,
        "discountAllowed": True,
        "eventId": "1",
        "eventTypeId": "7",
        "inPlay": False,
        "marketBaseRate": 5.0,
        "marketTime": off_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "numberOfActiveRunners": 1,
        "numberOfWinners": 1,
        "persistenceEnabled": True,
        "regulators": ["MR_INT"],
        "runnersVoidable": False,
        "status": "OPEN",
        "timezone": "Europe/London",
        "turnInPlayEnabled": False,
        "version": 1,
        "countryCode": "GB",
        "venue": "Synthetic Park",
        "marketType": "WIN",
        "eventName": "Synthetic Test Race",
        "suspendTime": off_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "runners": [{"id": selection_id, "sortPriority": 1, "status": "ACTIVE"}],
    }

    lines: list[str] = []
    # Full image, well before the strategy's placement window, establishing
    # the market as OPEN with our one runner ACTIVE.
    first_pt = off_epoch_ms - 400_000
    lines.append(_line(first_pt, market_id, {"marketDefinition": dict(base_definition), "img": True}))

    for seconds_before, ltp in ltp_ticks:
        pt = off_epoch_ms - int(seconds_before * 1000)
        lines.append(_line(pt, market_id, {"rc": [{"ltp": ltp, "id": selection_id}]}))

    close_definition = dict(base_definition)
    close_definition["status"] = "CLOSED"
    close_definition["version"] = 2
    close_definition["runners"] = [
        {"id": selection_id, "sortPriority": 1, "status": "WINNER" if winner else "LOSER"}
    ]
    close_pt = off_epoch_ms + 120_000
    lines.append(_line(close_pt, market_id, {"marketDefinition": close_definition}))

    return "\n".join(lines) + "\n"


def write_synthetic_market(path, market_id: str, selection_id: int, ltp_ticks, winner: bool = True) -> None:
    off_dt = datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
    content = build_synthetic_market(market_id, selection_id, off_dt, ltp_ticks, winner)
    path.write_text(content)
