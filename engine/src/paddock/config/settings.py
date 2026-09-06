"""Engine-wide runtime settings, loaded from environment / .env.

Safety: PADDOCK_MODE gates what the engine is allowed to do. `live` is
hard-disabled in Phase 0 — see LIVE_ENABLED below. Do not remove that
guard as part of adding a feature; it is only meant to come out in Phase 1
alongside real cert-based live trading, real risk controls, and explicit
sign-off from Gary.
"""
from __future__ import annotations

from enum import Enum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Phase 0 kill switch. Even a correctly configured live app key + ack cannot
# reach live order placement while this is False. Flip only in Phase 1.
LIVE_ENABLED = False

LIVE_ACK_PHRASE = "I_UNDERSTAND_REAL_MONEY"


class PaddockMode(str, Enum):
    REPLAY = "replay"
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PADDOCK_", extra="ignore")

    mode: PaddockMode = PaddockMode.REPLAY

    live_ack: str | None = None

    betfair_username: str | None = None
    betfair_password: str | None = None
    betfair_app_key: str | None = None
    betfair_live_app_key: str | None = None
    betfair_cert_file: str | None = None
    betfair_key_file: str | None = None
    betfair_certs_dir: str | None = None

    api_cors_origin: str = "http://localhost:5173"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    data_dir: str = "/data"

    @model_validator(mode="after")
    def _guard_live_mode(self) -> "Settings":
        if self.mode is PaddockMode.LIVE:
            if not LIVE_ENABLED:
                raise RuntimeError(
                    "PADDOCK_MODE=live is disabled in Phase 0. Real-money order "
                    "placement is physically impossible in this build (see "
                    "docs/phase1.md). This is not a bug — do not bypass it."
                )
            if self.live_ack != LIVE_ACK_PHRASE:
                raise RuntimeError(
                    f"PADDOCK_MODE=live requires PADDOCK_LIVE_ACK={LIVE_ACK_PHRASE!r}."
                )
            if not self.betfair_live_app_key:
                raise RuntimeError("PADDOCK_MODE=live requires PADDOCK_BETFAIR_LIVE_APP_KEY.")
        return self


def get_settings() -> Settings:
    return Settings()
