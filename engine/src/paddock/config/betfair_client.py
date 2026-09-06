"""Shared betfairlightweight APIClient construction + login.

Used by paddock.data.historic (step 2) and paddock.paper (step 3). Cert-based
login is non-interactive: `client.login()` uses cert_files. Without certs we
fall back to `client.login_interactive()` (username/password, prompts for
2FA in a browser/terminal). Confirmed against betfairlightweight 2.24.0
source — apiclient.py wires both endpoints regardless of which is used.
"""
from __future__ import annotations

import betfairlightweight

from paddock.config.settings import Settings


class BetfairCredentialsError(RuntimeError):
    pass


def make_api_client(settings: Settings) -> betfairlightweight.APIClient:
    if not settings.betfair_username or not settings.betfair_app_key:
        raise BetfairCredentialsError(
            "PADDOCK_BETFAIR_USERNAME and PADDOCK_BETFAIR_APP_KEY are required."
        )
    cert_files = None
    if settings.betfair_cert_file and settings.betfair_key_file:
        cert_files = (settings.betfair_cert_file, settings.betfair_key_file)
    return betfairlightweight.APIClient(
        username=settings.betfair_username,
        password=settings.betfair_password,
        app_key=settings.betfair_app_key,
        certs=settings.betfair_certs_dir,
        cert_files=cert_files,
        lightweight=False,
    )


def login(client: betfairlightweight.APIClient, settings: Settings) -> None:
    has_certs = bool(settings.betfair_cert_file and settings.betfair_key_file)
    if has_certs:
        client.login()
    else:
        client.login_interactive()
