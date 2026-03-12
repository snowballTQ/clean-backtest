# Clean Backtest Package

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/snowballTQ/clean-backtest/blob/main/clean_backtest_colab.ipynb)

This folder contains a cleaned and distributable version of the backtest code.

- GitHub repository: `https://github.com/snowballTQ/clean-backtest`
- Colab notebook: `https://colab.research.google.com/github/snowballTQ/clean-backtest/blob/main/clean_backtest_colab.ipynb`

## Files

- `backtest.py`
  - Shared loaders, strategy logic, metrics, and CSV writers.
- `run_core_analysis.py`
  - Compares index buy-and-hold, leveraged buy-and-hold, and three-day SMA timing strategies.
- `run_staged_analysis.py`
  - Runs staged exit variants that move realized proceeds into a proxy equity series.
- `run_all.py`
  - Runs both scripts in sequence.
- `run_custom_analysis.py`
  - Lets you choose your own date range, leverage values, cost assumptions, timing parameters, and staged exit settings.
- `clean_backtest_colab.ipynb`
  - Colab notebook that clones the repo, lets you set parameters from a form, runs the custom analysis, previews outputs, and downloads the result archive.

## Environment

- Python 3.11 or newer
- No external Python packages required

## Commands

Run everything:

```bash
python run_all.py
```

On Colab:

```bash
!python run_all.py
```

Open directly in Colab:

```text
https://colab.research.google.com/github/snowballTQ/clean-backtest/blob/main/clean_backtest_colab.ipynb
```

Run only the core comparison:

```bash
python run_core_analysis.py
```

Run only the staged strategy comparison:

```bash
python run_staged_analysis.py
```

Run a custom analysis:

```bash
python run_custom_analysis.py --start-date 2000-01-03 --end-date 2026-03-09 --leverages 2,3 --include-staged --output-name custom_analysis
```

## Outputs

Generated files are written to:

- `%USERPROFILE%\\backtest_outputs\\core_analysis\\`
- `%USERPROFILE%\\backtest_outputs\\staged_analysis\\`

This output location avoids issues that can happen when the project itself lives inside a non-ASCII path.

## Default assumptions

- Date range: `1985-10-01` to `2026-03-09`
- Commission: `0.10%` per side
- Tax: `22%` on net realized gains by calendar year
- 3x financing cost: `2 x (DFF + 1%) + 0.95%`
- 2x financing cost: `1 x (DFF + 1%) + 0.95%`
- Cash earns `DFF` on an ACT/360 basis
- Three-day timing rule: enter after three consecutive closes above the 200-day moving average; exit on a close below the 200-day moving average

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
