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
def auth() -> None:
    """Account/auth diagnostics — read-only, never prints secrets."""


@auth.command("check")
def auth_check() -> None:
    """Log in (cert if configured, else interactive), print account status
    + balance, and confirm the configured app key is DELAYED not LIVE."""
    from paddock.auth import check
    from paddock.config.settings import get_settings

    settings = get_settings()
    if not settings.betfair_password:
        raise click.ClickException(
            "PADDOCK_BETFAIR_PASSWORD is not set in engine/.env — fill it in first."
        )

    result = check(settings)

    click.echo(f"Logged in as: {settings.betfair_username}")
    click.echo(f"Account currency: {result['currency_code']}")
    click.echo(f"Discount rate: {result['discount_rate']}")
    click.echo(f"Available to bet balance: {result['available_to_bet_balance']}")
    click.echo(f"Exposure: {result['exposure']}")
    click.echo(f"Event types visible: {result['event_type_count']}")
    click.echo(f"App key type: {result['app_key_type']}")
    if result["app_key_type_raw_version"] is not None:
        click.echo(f"  (matched key version entry: {result['app_key_type_raw_version']})")
    if result["app_key_type"] == "LIVE":
        click.echo(
            "WARNING: this looks like a LIVE app key, not delayed. "
            "PADDOCK_MODE=live is hard-disabled regardless (see settings.py), "
            "but double check you got the right key from Betfair."
        )
    elif result["app_key_type"] == "UNKNOWN":
        click.echo(
            "Could not confirm key type from getDeveloperAppKeys — check manually "
            "at https://myaccount.betfair.com/accountdetails/mydetails under "
            "'Application Keys'."
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
@click.option(
    "--country",
    "countries",
    multiple=True,
    default=(),
    help="Filter to these countryCode(s), e.g. --country GB. Repeatable. Default: no filter.",
)
@click.option(
    "--market-type",
    "market_types",
    multiple=True,
    default=(),
    help="Filter to these marketType(s), e.g. --market-type WIN. Repeatable. Default: no filter.",
)
def data_unpack(
    archive: Path, dest: Path | None, countries: tuple[str, ...], market_types: tuple[str, ...]
) -> None:
    """Unpack a downloaded .tar/.bz2 historic file into plain JSON streams.
    Markets that don't match --country/--market-type are never written."""
    from paddock.config.settings import get_settings
    from paddock.data import historic

    settings = get_settings()
    resolved_dest = dest if dest is not None else Path(settings.data_dir)
    result = historic.unpack(
        archive,
        resolved_dest,
        countries=list(countries) or None,
        market_types=list(market_types) or None,
    )
    summary = historic.summarize(result)

    click.echo(f"Unpacked {summary['market_count']} market file(s) into {resolved_dest}")
    from_time, to_time = summary["date_range"]
    click.echo(f"Date range: {from_time} .. {to_time}")
    click.echo(f"Total size: {summary['total_size_bytes'] / 1024:.1f} KiB")
    click.echo(f"Data plan: {summary['data_plans']}")

    click.echo("\nPer plan/month:")
    for group_name, g in summary["groups"].items():
        gf, gt = g["date_range"]
        click.echo(
            f"  {group_name}: {g['market_count']} market(s), {gf} .. {gt}, "
            f"{g['total_size_bytes'] / 1024:.1f} KiB, venues={g['venues']}"
        )

    if summary["skipped_groups"]:
        click.echo("\nSkipped (entirely non-matching country):")
        for s in summary["skipped_groups"]:
            click.echo(
                f"  {s['data_plan']}/{s['year']}-{s['month']}: {s['market_count']} market(s), "
                f"{s['total_bytes'] / 1024:.1f} KiB skipped"
            )

    if summary["duplicates_skipped"]:
        click.echo(f"\n{len(summary['duplicates_skipped'])} duplicate(s) already on disk, byte-identical, skipped.")

    if summary["conflicts"]:
        click.echo(f"\nWARNING: {len(summary['conflicts'])} conflict(s) — same market_id/plan, DIFFERENT content, NOT overwritten:")
        for c in summary["conflicts"]:
            click.echo(f"  {c['data_plan']}/{c['market_id']}: existing={c['existing_sha256'][:12]} new={c['new_sha256'][:12]} at {c['path']}")


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
@click.option(
    "--fill-model",
    type=click.Choice(["ladder", "ltp_cross"]),
    default=None,
    help="Defaults to config/engine.yaml's fill_model. ladder needs Advanced/Pro "
    "plan data (order-book depth); ltp_cross is the optimistic Basic Plan "
    "approximation — see config/engine.yaml.",
)
@click.option(
    "--show-orders",
    is_flag=True,
    default=False,
    help="Print every matched order and each market's cleared() P&L at the end.",
)
def sim_run(
    strategy: str, data_path: Path, speed: float, fill_model: str | None, show_orders: bool
) -> None:
    from paddock.config.engine_config import load_engine_config
    from paddock.config.settings import get_settings
    from paddock.config.strategies_config import load_strategy_params
    from paddock.sim.harness import FillModelError, discover_market_files, run_simulation
    from paddock.strategies.registry import get_strategy_class

    settings = get_settings()
    engine_config = load_engine_config()
    resolved_fill_model = fill_model or engine_config.fill_model
    strategy_cls = get_strategy_class(strategy)
    strategy_kwargs = load_strategy_params(strategy)
    market_files = discover_market_files(data_path)
    if not market_files:
        raise click.ClickException(f"No market files found under {data_path}")

    try:
        run_id = run_simulation(
            strategy_cls,
            market_files,
            speed=speed,
            commission_rate=engine_config.commission_rate,
            fill_model=resolved_fill_model,
            data_dir=Path(settings.data_dir),
            mode=settings.mode.value,
            strategy_kwargs=strategy_kwargs,
        )
    except FillModelError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Run {run_id} complete ({len(market_files)} market file(s)), fill_model={resolved_fill_model}")
    if resolved_fill_model == "ltp_cross":
        click.echo(
            "NOTE: fill_model=ltp_cross — the P&L above is an OPTIMISTIC UPPER BOUND, "
            "not a backtest result. No partial fills, no queue position modelled."
        )

    if show_orders:
        from paddock.sim.store import connect

        with connect(Path(settings.data_dir)) as con:
            run = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            click.echo(f"\nrun_pnl={run['run_pnl']}")

            markets = con.execute(
                "SELECT * FROM run_markets WHERE run_id = ? ORDER BY market_id", (run_id,)
            ).fetchall()
            click.echo("\nPer-market (from flumine's own cleared()):")
            for m in markets:
                click.echo(
                    f"  {m['market_id']}: profit={m['market_pnl']} commission={m['commission']} "
                    f"bet_count={m['bet_count']}"
                )

            orders = con.execute(
                "SELECT * FROM run_orders WHERE run_id = ? ORDER BY market_id", (run_id,)
            ).fetchall()
            click.echo(f"\nOrders ({len(orders)}):")
            for o in orders:
                click.echo(
                    f"  {o['market_id']} {o['side']:4s} {o['price']:>6} matched={o['matched_size']:>5}/{o['size']:<5} "
                    f"status={o['status']:<18} profit={o['profit']}"
                )


if __name__ == "__main__":
    main()
