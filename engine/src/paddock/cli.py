"""`paddock` CLI entry point.

Subcommand groups are added incrementally as their part of the build lands:
`data` (step 2), `sim` (step 2), `paper` (step 3). `api` is wired up now
since step 1 is bus + API + UI Floor.
"""
from __future__ import annotations

import click
import uvicorn


@click.group()
def main() -> None:
    """PADDOCK — Betfair trading engine and visual control room."""


@main.command()
@click.option("--host", default=None, help="Override PADDOCK_API_HOST")
@click.option("--port", default=None, type=int, help="Override PADDOCK_API_PORT")
@click.option("--reload", is_flag=True, default=False)
def api(host: str | None, port: int | None, reload: bool) -> None:
    """Run the FastAPI server (bus + REST + /events websocket)."""
    from paddock.config.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "paddock.api.main:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
