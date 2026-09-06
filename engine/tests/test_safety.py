import pytest

from paddock.config.settings import LIVE_ENABLED, PaddockMode, Settings


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
