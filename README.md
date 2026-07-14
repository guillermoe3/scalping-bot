# BTC Scalping Bot

An asyncio Python bot for trading BTC/USDT on Binance Futures: regime detection, an entry gate
harness (spread/trend/CVD), ATR-based risk management, post-only maker execution and safety
rails — currently with **no adopted entry trigger** (see below). Includes a backtesting
harness that replays real historical Binance data through the exact same strategy code used live.

> **Disclaimer:** This is a research/educational project. Trading cryptocurrency carries
> substantial risk of loss. Validate extensively in `PAPER_MODE` and via backtesting before
> ever pointing this at real capital. Nothing here is financial advice.
>
> The signal clock is the 15m candle; this bot is an intraday swing system, not a sub-minute
> scalper (see docs/revisiones/ for the cost analysis that motivated this).

## How the strategy works

1. **Regime detection** (`regime.py`) — a hysteresis-protected state machine classifies the
   market into one of three regimes, requiring several consecutive confirming candles before
   committing to a transition (so noise doesn't flip it back and forth):
   - `BREAKOUT` — a large-bodied candle (>= 1.5x ATR)
   - `TIGHT_CHANNEL` — low-volatility, trending compression
   - `TRADING_RANGE` — two-sided range, confirmed by liquidity sweeps at both extremes
2. **Entry signal** (`signals.py: check_entry_signal`)

   **Current signal status: no entry trigger is adopted.** The original squeeze
   hypothesis was rejected with pre-registered criteria after a clean ablation
   (`backtest_runs/ablation-2026-07-14.md`); the bot deliberately does not trade
   until a new signal passes the base-rate studies and the ablation harness
   (see `docs/superpowers/specs/2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md`).
   Risk management, execution (post-only maker entries), safety rails and the
   backtest harness remain fully operational.
3. **Entry gate harness** (`signals.py: _passes_gates`) — kept fully wired and unit-tested so
   the next adopted signal has a reusable, backtest=live-consistent set of gates to run
   through: an acceptable spread, no opposing 1h-equivalent trend (EMA-80 on 15m closes), and
   no CVD divergence against the trade. The CVD gate is implemented but disabled by default
   (the 2026-07-14 ablation showed it vetoing good trades); it can be re-enabled per run via
   `backtest.py --enable-gate cvd`. The macro filter (BTC/SPY correlation) and the order-book
   imbalance gate were both removed — neither could be exercised by the backtest engine, which
   made their live behaviour unauditable.
4. **Risk management** (`risk.py`) — fixed-fractional sizing (0.5% account risk per trade),
   ATR-based stop loss and a 2R first target, 50% partial close at TP1, a breakeven stop after
   0.8 ATR of profit, ATR "breathing" stop expansion if volatility grows, a structural
   swing-point trailing stop, a 225-minute (15 bars of 15m) time exit, and a
   momentum-collapse abort (45 minutes / 3 bars of 15m).
5. **Execution** (`execution.py`) — entries rest as post-only limit orders at the touch
   (maker fee); in paper/backtest they fill only when price trades through the limit, and
   expire unfilled after a timeout. Exits (stop, target, time, momentum) cross the spread
   as market orders (taker fee). Live mode routes the entry as a Binance Futures GTX
   (post-only) order and polls for the fill.
6. **Safety** (`safety.py`) — persists PnL/position state to disk, enforces a daily kill switch
   (halts new entries after a -2% daily loss or 3 consecutive losses until the next UTC day), and
   on startup reconciles the persisted position against what the exchange actually reports,
   refusing to run if they disagree.

## Architecture

`data_feed.py` (live) and `backtest_feed.py` (historical replay) both emit the same
`on_trade` / `on_candle_1m` / `on_candle_5m` / `on_candle_15m` event interface, so
`main.wire_strategy` — the function that wires indicators, regime, signals, and execution
together — runs completely unmodified in either live trading or a backtest. Time-based logic
(risk exits, momentum abort, the daily kill switch) is driven through `clock.py`, an injectable
clock that backtests can fast-forward deterministically over simulated event time.

| File | Responsibility |
|---|---|
| `main.py` | Wires strategy event handlers (`wire_strategy`) and runs the live bot |
| `config.py` | All tunable strategy and risk parameters |
| `state.py` | `MarketState`, `Position`, `Candle` and other shared dataclasses |
| `data_feed.py` | Live Binance WebSocket feed (trades, klines, order book) |
| `indicators.py` | ATR, regime-aware EMA, swing point detection |
| `regime.py` | Regime state machine + 1h-equivalent trend bias |
| `signals.py` | Entry signal (currently none adopted) + the gate harness (spread/trend/CVD) |
| `momentum.py` | Volume velocity tracking + momentum-collapse abort |
| `order_flow.py` | CVD divergence detection |
| `risk.py` | Position sizing, stop/target levels, dynamic stop management |
| `execution.py` | Order routing (paper/live) via `ExecutionEngine` |
| `safety.py` | State persistence, daily kill switch, exchange reconciliation |
| `clock.py` | Injectable clock for live wall-clock vs. simulated backtest time |
| `backtest_feed.py` | Historical kline/trade fetch (`ccxt`), caching, and replay |
| `backtest_report.py` | Trade summary statistics + CSV trade log writer |
| `backtest.py` | Backtest CLI entry point |
| `tests/` | Unit test suite (pytest) |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Edit `.env`:

```
PAPER_MODE=true        # set to false only when ready for live trading
LOG_LEVEL=INFO          # DEBUG shows every 1m candle line, INFO shows signals and trades
BINANCE_API_KEY=...     # only required when PAPER_MODE=false
BINANCE_SECRET=...
```

## Running the live bot

```bash
python main.py
```

Starts in paper mode by default — no real orders are sent; paper entries rest as post-only limit
orders that fill only when price trades through the limit (and expire unfilled after a timeout);
paper exits are simulated by crossing the live bid/ask spread. Set `PAPER_MODE=false` with real Binance Futures API credentials to trade live, and only after thorough backtesting and paper-trading validation.

## Backtesting

Replay real historical Binance data through the unmodified strategy:

```bash
python backtest.py --start 2024-01-01 --end 2024-01-08 --out backtest_trades.csv
```

Options:

- `--start` / `--end` — UTC dates (`YYYY-MM-DD`); start inclusive, end exclusive
- `--balance` — starting paper balance (default 10,000 USDT)
- `--spread-pct` — synthetic spread as a fraction of price (no historical order-book depth
  exists, so spread is simulated)
- `--out` — trade log CSV path (default `backtest_trades.csv`)
- `--no-cache` — bypass the local `backtest_cache/` cache and re-fetch from Binance

Prints a console summary (trade count, win rate, total net P&L, profit factor, max drawdown, max
consecutive losses) and writes a per-trade CSV log. Historical klines/trades are cached under
`backtest_cache/` after the first fetch, so re-running the same date range is near-instant.

## Testing

```bash
pytest -q
```

The suite covers indicators, regime detection, signal gating, risk/execution, the safety/kill-switch
state machine, and the backtesting harness end-to-end.

## Design docs

Specs and step-by-step implementation plans for major features live under
`docs/superpowers/specs/` and `docs/superpowers/plans/`.
