# Clean Backtest Toolbox

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/snowballTQ/clean-backtest/blob/main/clean_backtest_colab.ipynb)

A general-purpose backtest toolbox for comparing long-only, leveraged, and moving-average timing ideas with configurable costs and date ranges.

- GitHub repository: `https://github.com/snowballTQ/clean-backtest`
- Colab notebook: `https://colab.research.google.com/github/snowballTQ/clean-backtest/blob/main/clean_backtest_colab.ipynb`

## What it can do

- Test different base histories such as `ndx`, `spx`, and `composite_splice`
- Compare multiple leverage values in one run
- Include or exclude financing costs
- Run buy-and-hold, price-vs-SMA timing, and dual-SMA crossover strategies
- Change date ranges, moving-average windows, confirmation days, commissions, taxes, and financing assumptions
- Export metrics, annual returns, drawdowns, equity curves, and the exact config used

## Files

- `backtest.py`
  - Shared data loaders, strategy simulations, and CSV writers
- `run_core_analysis.py`
  - Reproduces the core benchmark comparisons
- `run_custom_analysis.py`
  - Main toolbox runner for custom periods, leverage values, and strategy settings
- `run_all.py`
  - Runs the bundled example scripts in sequence
- `clean_backtest_colab.ipynb`
  - Colab notebook with editable form inputs

## Environment

- Python 3.11 or newer
- No external Python packages required

## Quick start

Open directly in Colab:

```text
https://colab.research.google.com/github/snowballTQ/clean-backtest/blob/main/clean_backtest_colab.ipynb
```

Or run locally:

```bash
python run_custom_analysis.py --base-series ndx,spx --include-base-series --leverages 2,3
```

## Useful commands

Run the benchmark set:

```bash
python run_core_analysis.py
```

Run the general toolbox with custom settings:

```bash
python run_custom_analysis.py ^
  --start-date 2000-01-03 ^
  --end-date 2026-03-09 ^
  --base-series ndx,spx ^
  --include-base-series ^
  --leverages 2,3 ^
  --price-sma-window 200 ^
  --price-entry-confirm-days 3 ^
  --fast-sma-window 50 ^
  --slow-sma-window 200 ^
  --output-name toolbox_example
```

## Main custom options

- `--base-series`
  - Comma-separated list such as `ndx`, `spx`, `composite_splice`
- `--include-base-series`
  - Include 1x base-series strategies
- `--leverages`
  - Comma-separated leverage values such as `2,3`
- `--include-zero-cost`
  - Also run zero-cost leveraged variants
- `--skip-cost-adjusted`
  - Disable cost-adjusted leveraged variants
- `--skip-buyhold`
  - Skip buy-and-hold
- `--skip-price-sma`
  - Skip price-vs-SMA timing
- `--skip-dual-sma`
  - Skip fast/slow SMA crossover
- `--price-sma-window`
  - Moving-average length for the price-vs-SMA strategy
- `--price-entry-confirm-days`
  - Consecutive closes above the SMA before entry
- `--price-exit-confirm-days`
  - Consecutive closes below the SMA before exit
- `--fast-sma-window`
  - Fast SMA length for the crossover strategy
- `--slow-sma-window`
  - Slow SMA length for the crossover strategy
- `--cross-entry-confirm-days`
  - Consecutive bullish crossover signals before entry
- `--cross-exit-confirm-days`
  - Consecutive bearish crossover signals before exit

## Outputs

Generated files are written to:

- `%USERPROFILE%\\backtest_outputs\\<output_name>\\metrics.csv`
- `%USERPROFILE%\\backtest_outputs\\<output_name>\\annual_returns.csv`
- `%USERPROFILE%\\backtest_outputs\\<output_name>\\drawdowns.csv`
- `%USERPROFILE%\\backtest_outputs\\<output_name>\\equity_curves.csv`
- `%USERPROFILE%\\backtest_outputs\\<output_name>\\config.json`

This output location avoids issues that can happen when the project itself lives inside a non-ASCII path.

## Default assumptions

- Default date range: `1985-10-01` to `2026-03-09`
- Commission: `0.10%` per side
- Tax: `22%` on net realized gains by calendar year
- 3x financing cost: `2 x (DFF + 1%) + 0.95%`
- 2x financing cost: `1 x (DFF + 1%) + 0.95%`
- Cash earns `DFF` on an ACT/360 basis

## Data sources

The package checks for local snapshots in `data/` first. If no snapshot is found, it fetches the original source.

- NDX: Stooq
- SPX: Stooq
- DFF: FRED
- NASDAQ Composite: FRED

## Benchmark values

These are useful for reproducibility checks on the core analysis.

- `NDX Buy and Hold`
  - CAGR: `13.6007%`
  - MDD: `-82.8972%`
- `Leveraged 3x Buy and Hold (cost-adjusted)`
  - CAGR: `9.7601%`
  - MDD: `-99.9847%`
- `Leveraged 2x Buy and Hold (cost-adjusted)`
  - CAGR: `15.0025%`
  - MDD: `-99.0071%`
- `Three-Day SMA Timing (cost-adjusted, 3x)`
  - CAGR: `10.7300%`
  - MDD: `-81.9522%`
