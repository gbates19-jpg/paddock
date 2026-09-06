"""Read-only account/auth diagnostics. Never logs, returns, or prints the
password or the app key itself — see _classify_app_key's redaction.
"""
from __future__ import annotations

from typing import Any

from betfairlightweight.filters import market_filter

from paddock.config.betfair_client import login, make_api_client
from paddock.config.settings import Settings

REDACTED = "***redacted***"


def check(settings: Settings) -> dict[str, Any]:
    client = make_api_client(settings)
    login(client, settings)
    try:
        funds = client.account.get_account_funds()
        details = client.account.get_account_details()
        event_types = client.betting.list_event_types(filter=market_filter())
        key_type, key_raw = _classify_app_key(client, settings.betfair_app_key)

        return {
            "logged_in": True,
            "currency_code": details.currency_code,
            "discount_rate": details.discount_rate,
            "available_to_bet_balance": funds.available_to_bet_balance,
            "exposure": funds.exposure,
            "event_type_count": len(event_types),
            "app_key_type": key_type,
            "app_key_type_raw_version": key_raw,
        }
    finally:
        client.logout()


def _classify_app_key(client, app_key: str | None) -> tuple[str, dict | None]:
    """Calls the (unwrapped by betfairlightweight) AccountAPING
    getDeveloperAppKeys operation directly, reusing the same auth headers
    and JSON-RPC plumbing client.account already uses for every other call.

    Confirmed from Betfair's own docs: a delayed key's version string is
    literally "1.0-DELAY" (support.developer.betfair.com "When should I use
    the Delayed or Live Application Key?"). The exact field name for a
    boolean equivalent isn't independently confirmed here, so this checks
    both a `delayData` flag (if present) and the "DELAY" substring in
    `version`, and returns whichever version entry matched — with the
    application key value itself redacted, since it's a secret.
    """
    if not app_key:
        return "UNKNOWN", None
    _, response_json, _ = client.account.request(
        "AccountAPING/v1.0/getDeveloperAppKeys", {}, None
    )
    apps = response_json.get("result", [])
    for app in apps:
        for version in app.get("appVersions", []):
            if version.get("applicationKey") == app_key:
                is_delayed = bool(version.get("delayData")) or "DELAY" in str(
                    version.get("version", "")
                ).upper()
                redacted = {**version, "applicationKey": REDACTED}
                return ("DELAYED" if is_delayed else "LIVE"), redacted
    return "UNKNOWN", None
