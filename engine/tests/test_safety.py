import pytest
from flumine.clients.clients import VenueType

from paddock.config.settings import LIVE_ENABLED, PaddockMode, Settings
from paddock.sim.clients import build_paper_client, build_replay_client
from paddock.sim.commission import compute_commission


def test_live_enabled_is_hardcoded_false():
    """Phase 0 must not be able to flip this at runtime — see docs/phase1.md."""
    assert LIVE_ENABLED is False


def test_live_mode_raises_even_with_full_ack(monkeypatch):
    monkeypatch.setenv("PADDOCK_MODE", "live")
    monkeypatch.setenv("PADDOCK_LIVE_ACK", "I_UNDERSTAND_REAL_MONEY")
    monkeypatch.setenv("PADDOCK_BETFAIR_LIVE_APP_KEY", "some-real-key")
    with pytest.raises(RuntimeError, match="disabled in Phase 0"):
        Settings()


def test_replay_mode_is_default():
    assert Settings().mode is PaddockMode.REPLAY


def test_replay_and_paper_clients_never_reach_real_execution():
    """flumine.clients.clients.Clients.simulated (flumine 3.2.0) routes to
    simulated_execution — never the real betting endpoint — whenever
    `client.VENUE == VenueType.SIMULATED or client.paper_trade`. Both of our
    client factories must satisfy that, structurally, independent of
    whatever a strategy does. The full "no code path calls placeOrders on
    the real client" guard (owed per the brief's Safety section) still needs
    a strategy that actually places orders to be meaningful end-to-end —
    that lands with step 3's BaselineFavouriteScalp. This test locks down
    the part of the guarantee that doesn't depend on a strategy existing."""
    replay_client = build_replay_client(commission_rate=0.02)
    assert replay_client.VENUE == VenueType.SIMULATED

    dummy_betting_client = type("DummyBettingClient", (), {"lightweight": False})()
    paper_client = build_paper_client(dummy_betting_client, commission_rate=0.02)
    assert paper_client.paper_trade is True


def test_commission_rate_never_defaults_to_five_percent():
    """DEFAULT_COMMISSION_BASE in flumine's BaseClient is 0.05 — make sure
    our factories always override it with the real account rate."""
    client = build_replay_client(commission_rate=0.02)
    assert client.commission_base == 0.02
    assert client.commission_base != 0.05
    assert compute_commission(100.0, client.commission_base) == 2.0
