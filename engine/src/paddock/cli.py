"""`paddock` CLI entry point.

Subcommand groups are added incrementally as their part of the build lands:
`data` + `sim` (step 2), `paper` (step 3). All path options use
click.Path(path_type=Path) rather than raw strings — the repo path itself
has a space in it, so anything that isn't pathlib from the start is a latent
bug (see tests/test_paths_with_spaces.py).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

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


@main.group()
def data() -> None:
    """Historic data fetch/unpack (Betfair historic data API, Basic Plan)."""


@data.command("fetch")
@click.option("--from-date", "from_date_str", required=True, help="YYYY-MM-DD")
@click.option("--to-date", "to_date_str", required=True, help="YYYY-MM-DD")
@click.option("--sport", default="Horse Racing")
@click.option("--plan", default="Basic Plan")
@click.option("--market-type", "market_types", multiple=True, default=("WIN",))
@click.option("--country", "countries", multiple=True, default=("GB",))
@click.option(
    "--store-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Defaults to <PADDOCK_DATA_DIR>/raw",
)
def data_fetch(
    from_date_str: str,
    to_date_str: str,
    sport: str,
    plan: str,
    market_types: tuple[str, ...],
    countries: tuple[str, ...],
    store_dir: Path | None,
) -> None:
    """Download purchased historic files. You must first "purchase" (free
    for Basic Plan) the data at https://historicdata.betfair.com."""
    from paddock.config.settings import get_settings
    from paddock.data import historic

    settings = get_settings()
    resolved_store_dir = store_dir if store_dir is not None else Path(settings.data_dir) / "raw"
    files = historic.fetch(
        settings,
        date.fromisoformat(from_date_str),
        date.fromisoformat(to_date_str),
        resolved_store_dir,
        sport=sport,
        plan=plan,
        market_types=list(market_types),
        countries=list(countries),
    )
    click.echo(f"Downloaded {len(files)} file(s) to {resolved_store_dir}")


@data.command("unpack")
@click.argument("archive", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--dest",
    type=click.Path(path_type=Path),
    default=None,
    help="Defaults to <PADDOCK_DATA_DIR> (files land under <year>/<month>/<market_id>)",
)
def data_unpack(archive: Path, dest: Path | None) -> None:
    """Unpack a downloaded .tar/.bz2 historic file into plain JSON streams."""
    from paddock.config.settings import get_settings
    from paddock.data import historic

    settings = get_settings()
    resolved_dest = dest if dest is not None else Path(settings.data_dir)
    written = historic.unpack(archive, resolved_dest)
    summary = historic.summarize(written)

    click.echo(f"Unpacked {summary['market_count']} market file(s) into {resolved_dest}")
    from_time, to_time = summary["date_range"]
    click.echo(f"Date range: {from_time} .. {to_time}")
    click.echo(f"Total size: {summary['total_size_bytes'] / 1024:.1f} KiB")
    click.echo("Venues:")
    for venue, count in summary["venues"].items():
        click.echo(f"  {venue}: {count}")


@main.group()
def sim() -> None:
    """Simulation harness (FlumineSimulation over historic files)."""


@sim.command("run")
@click.option("--strategy", required=True, help="Registered strategy name, see paddock.strategies.registry")
@click.option(
    "--data",
    "data_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="A single market file, or a directory to search recursively",
)
@click.option(
    "--speed",
    default=20.0,
    type=float,
    help="Market-seconds per real-second; 0 = as fast as possible",
)
def sim_run(strategy: str, data_path: Path, speed: float) -> None:
    from paddock.config.engine_config import load_engine_config
    from paddock.config.settings import get_settings
    from paddock.sim.harness import discover_market_files, run_simulation
    from paddock.strategies.registry import get_strategy_class

    settings = get_settings()
    engine_config = load_engine_config()
    strategy_cls = get_strategy_class(strategy)
    market_files = discover_market_files(data_path)
    if not market_files:
        raise click.ClickException(f"No market files found under {data_path}")

    run_id = run_simulation(
        strategy_cls,
        market_files,
        speed=speed,
        commission_rate=engine_config.commission_rate,
        data_dir=Path(settings.data_dir),
    )
    click.echo(f"Run {run_id} complete ({len(market_files)} market file(s))")


if __name__ == "__main__":
    main()
