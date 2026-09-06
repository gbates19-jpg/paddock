# Phase 1: enabling real-money live trading

This is a plan, not a status report. Nothing in this document is
implemented. It exists because `paddock.config.settings` and
`paddock.cli` both point here when they refuse to do something — this is
where "why" and "what it'd take" live instead of being repeated inline at
every guard.

Phase 0 (this build) trades two ways only: `replay` (historic files) and
`paper` (flumine's simulated-fill client against a real, currently-live
market — no historic file needed, no money moved). `live` — real order
placement against a real account — is **physically disabled**, not just
defaulted off. Phase 1 is the work required to responsibly remove that.

## The three independent gates today

`Settings._guard_live_mode` (`engine/src/paddock/config/settings.py`)
checks all three before it will even construct a `live`-mode `Settings`
object — code that runs before any strategy, any client, any order:

1. `LIVE_ENABLED = False`, a hardcoded module constant, not an env var.
   No amount of configuration can flip it; only a code change can.
2. `PADDOCK_LIVE_ACK` must exactly equal `I_UNDERSTAND_REAL_MONEY`.
3. `PADDOCK_BETFAIR_LIVE_APP_KEY` must be set (the separate, paid live
   key — never the free delayed key `PADDOCK_BETFAIR_APP_KEY` used
   today).

`tests/test_safety.py::test_live_enabled_is_hardcoded_false` and
`test_live_mode_raises_even_with_full_ack` pin this down: the second test
sets *all three* env vars correctly and still asserts a `RuntimeError`,
because `LIVE_ENABLED` can't be satisfied from the environment at all.
Any PR that makes those two tests pass without deliberately editing
`LIVE_ENABLED` should be treated as a bug in the PR, not progress.

## What actually has to happen before that flag flips

Roughly the order it needs to happen in — each one blocks the next in
practice, not just on paper:

1. **A real live app key.** Betfair's live key is a one-time paid
   purchase (~£299, confirmed against Gary's own account), separate from
   the free delayed key this build already uses for historic data +
   diagnostics. `paddock auth check` already classifies whatever key is
   configured and prints a warning if it looks LIVE rather than DELAYED
   (`engine/src/paddock/cli.py::auth_check`) — that check exists
   specifically so this step is verifiable before anything else is built
   on top of it.

2. **Cert-based non-interactive login, for real.** `Settings` already has
   the fields (`betfair_cert_file`, `betfair_key_file`,
   `betfair_certs_dir`) and `paddock.config.betfair_client.login` already
   branches on them, but nothing has exercised this against Betfair's
   real cert-login endpoint yet — it's only ever been used with
   `login_interactive()` (username/password + 2FA prompt) so far. Betfair
   requires certs to be generated and the public half uploaded to the
   account before cert login works at all. Needs its own real-account
   verification pass the same way historic data's plan detection got one
   (see README.md's Data section) before anything live depends on it.

3. **A `paddock.paper` implementation.** The module exists
   (`engine/src/paddock/paper/__init__.py`) but is empty — step 3 landed
   `BaselineFavouriteScalp` and proved it against replay/historic data and
   synthetic markets only (`tests/test_baseline_strategy.py`,
   `test_baseline_flat_invariant.py`, `test_baseline_ladder_flat_invariant.py`).
   None of that has ever run against a live, currently-ticking market — a
   real delayed or streaming feed behaves differently in ways historic
   replay can't fully stand in for (timing jitter, feed gaps,
   reconnects). Paper trading — flumine's `paper_trade=True` client
   against a live market, zero real stake, real timing — is the step that
   proves the strategy survives contact with a live feed before it's
   allowed anywhere near `build_live_client`.

4. **A `build_live_client`.** `paddock.sim.clients` currently only
   exports `build_replay_client` and `build_paper_client`
   (`test_replay_and_paper_clients_never_reach_real_execution` locks down
   that both structurally route away from real execution — see flumine's
   `Clients.simulated` gate in that test's docstring). A third factory
   that constructs a real `BetfairClient` and wires it the way flumine
   expects for live execution doesn't exist yet, deliberately — writing
   it is itself a Phase 1 task, not something to have lying around
   unused in Phase 0.

5. **Real risk controls, sized to the account, not the demo.**
   `config/strategies.yaml`'s `max_order_exposure: 50` and `stake: 2.0`
   are reasonable numbers for proving the strategy works, not numbers
   derived from Gary's actual bankroll or risk tolerance. Phase 1 needs:
   a position-size/exposure ceiling actually tied to
   `get_account_funds().available_to_bet_balance` (which `paddock auth
   check` already reads and prints, so the number is already one call
   away), and a global kill-switch reachable independently of any one
   strategy's own logic — something an operator (or a future automated
   monitor) can hit to stop new order placement account-wide without
   having to find and kill the right process.

6. **Unattended-operation story.** Phase 0 assumes a human is watching
   the control room while a replay or paper run plays out. Live trading
   against a real account run unattended (the actual point of automating
   it) means: crash recovery and alerting if the engine process dies
   mid-position (a resting order becomes a real position no one is
   watching), and some answer to "is it still alive and trading
   correctly" that doesn't require someone to have the control room
   open. None of this exists today — the bus
   worker heartbeats in `paddock.bus.events` currently exist for UI
   display, not for alerting anyone.

7. **Explicit sign-off from Gary.** Stated directly in
   `settings.py`'s module docstring: `LIVE_ENABLED` is "only meant to come
   out in Phase 1 alongside real cert-based live trading, real risk
   controls, and explicit sign-off from Gary." That's a manual gate, not
   a checklist item something else can tick off — 1-6 above are what
   should exist *before* asking for that sign-off, not a substitute for
   it.

## What flipping the switch actually looks like

A single-line code change to `LIVE_ENABLED = True` in a PR whose
description links back to this document and states which of the six
items above are done, plus the two `test_safety.py` tests above updated
to reflect the new intended behaviour (they currently assert the
opposite on purpose). Nothing about `PaddockMode.LIVE` needs to be an
environment-only toggle even after Phase 1 lands — `PADDOCK_LIVE_ACK` and
a real live app key still gate every individual run, the same shape as
today, just no longer blocked by the hardcoded constant underneath them.

## Explicitly out of scope for Phase 1 itself

- Multi-strategy or multi-account support — Phase 1 is "make the one
  proven strategy safe to run live," not a platform rewrite.
- Anything about the historic-data fill models (`ladder`/`ltp_cross`,
  see README.md) — a live stream has real order-book depth by
  construction, so fill-model selection is a Phase-0-only concern; live
  execution goes through flumine's real `BetfairClient`, not
  `SimulatedMiddleware`, and doesn't choose between the two at all.
