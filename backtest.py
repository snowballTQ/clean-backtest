from __future__ import annotations

import csv
import math
import urllib.request
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_ROOT = Path.home() / "backtest_outputs"

DEFAULT_START_DATE = date(1985, 10, 1)
DEFAULT_END_DATE = date(2026, 3, 9)

COMMISSION_RATE = 0.001
TAX_RATE = 0.22
EXPENSE_RATIO = 0.0095
BORROW_SPREAD = 1.0

SMA_WINDOW = 200
ENTRY_CONFIRM_DAYS = 3
SMALL_EXIT_THRESHOLDS = [1.10, 1.25, 1.50]
LARGE_EXIT_START = 2.0

NDX_URL = "https://stooq.com/q/d/l/?s=%5Endx&i=d"
SPX_URL = "https://stooq.com/q/d/l/?s=%5Espx&i=d"
DFF_TEXT_URL = "https://fred.stlouisfed.org/data/DFF.txt"
NASDAQ_COMPOSITE_TEXT_URL = "https://fred.stlouisfed.org/data/NASDAQCOM.txt"


@dataclass
class MetricRow:
    name: str
    final_value: float
    cagr: float
    mdd: float
    calmar: float
    trades: int
    time_in_market: float


@dataclass
class DrawdownEpisode:
    strategy: str
    rank: int
    peak_date: date
    trough_date: date
    recovery_date: date | None
    drawdown: float
    peak_to_trough_days: int
    peak_to_recovery_days: int | None
    recovered: bool


def ensure_output_dir(name: str) -> Path:
    path = OUTPUT_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def read_snapshot_or_fetch(snapshot_names: list[str], fallback_url: str) -> str:
    for name in snapshot_names:
        path = DATA_DIR / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return fetch_text(fallback_url)


def parse_stooq_csv(raw_text: str, start_date: date, end_date: date) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    reader = csv.DictReader(raw_text.splitlines())
    for row in reader:
        try:
            row_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
            close = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if start_date <= row_date <= end_date:
            rows.append((row_date, close))
    if not rows:
        raise RuntimeError("No price rows parsed.")
    return rows


def parse_fred_series(
    raw_text: str,
    value_column: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []

    if "observation_date" in raw_text:
        reader = csv.DictReader(raw_text.splitlines())
        for row in reader:
            try:
                row_date = datetime.strptime(row["observation_date"], "%Y-%m-%d").date()
                raw_value = row.get(value_column, "")
            except (KeyError, TypeError, ValueError):
                continue
            if not raw_value or raw_value == ".":
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if start_date and row_date < start_date:
                continue
            if end_date and row_date > end_date:
                continue
            rows.append((row_date, value))
    else:
        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("#"):
                continue
            try:
                raw_date, raw_value = line[1:].split("|", 1)
                row_date = datetime.strptime(raw_date.strip(), "%Y-%m-%d").date()
                value = float(raw_value.strip())
            except (ValueError, TypeError):
                continue
            if start_date and row_date < start_date:
                continue
            if end_date and row_date > end_date:
                continue
            rows.append((row_date, value))

    if not rows:
        raise RuntimeError(f"No rows parsed for {value_column}.")
    return rows


def load_index_rows(start_date: date = DEFAULT_START_DATE, end_date: date = DEFAULT_END_DATE) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(["ndx.csv"], NDX_URL)
    return parse_stooq_csv(raw_text, start_date, end_date)


def load_proxy_rows(start_date: date, end_date: date) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(["spx.csv"], SPX_URL)
    return parse_stooq_csv(raw_text, start_date, end_date)


def load_spx_rows(start_date: date, end_date: date) -> list[tuple[date, float]]:
    return load_proxy_rows(start_date, end_date)


def load_rate_rows(start_date: date | None = None, end_date: date | None = None) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(["dff.csv", "dff.txt"], DFF_TEXT_URL)
    return parse_fred_series(raw_text, "DFF", start_date, end_date)


def load_composite_rows(start_date: date | None = None, end_date: date | None = None) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(["nasdaqcom.csv", "nasdaqcom.txt"], NASDAQ_COMPOSITE_TEXT_URL)
    return parse_fred_series(raw_text, "NASDAQCOM", start_date, end_date)


def resolve_base_rows(
    base_series_name: str,
    start_date: date,
    end_date: date,
) -> list[tuple[date, float]]:
    if base_series_name == "ndx":
        return load_index_rows(start_date, end_date)
    if base_series_name == "spx":
        return load_spx_rows(start_date, end_date)
    if base_series_name == "composite_splice":
        later_rows = load_index_rows(start_date, end_date)
        early_rows = load_composite_rows(None, end_date)
        splice_date = later_rows[0][0]
        return build_spliced_series(early_rows, later_rows, splice_date)
    raise ValueError(f"Unsupported base series: {base_series_name}")


def normalize_series(series: list[tuple[date, float]]) -> list[tuple[date, float]]:
    first_price = series[0][1]
    return [(row_date, price / first_price) for row_date, price in series]


def get_latest_value(target_date: date, series_dates: list[date], series_map: dict[date, float]) -> float:
    idx = bisect_right(series_dates, target_date) - 1
    if idx < 0:
        raise RuntimeError(f"No observation on or before {target_date.isoformat()}.")
    return series_map[series_dates[idx]]


def annual_financing_rate(dff_percent: float, leverage: float) -> float:
    borrow_multiple = max(leverage - 1.0, 0.0)
    expense_ratio = EXPENSE_RATIO if leverage > 1.0 else 0.0
    return borrow_multiple * ((dff_percent + BORROW_SPREAD) / 100.0) + expense_ratio


def interval_cash_multiplier(days: int, dff_percent: float) -> float:
    return math.exp((dff_percent / 100.0) * days / 360.0)


def interval_cost_multiplier(days: int, dff_percent: float, leverage: float) -> float:
    return math.exp(-annual_financing_rate(dff_percent, leverage) * days / 360.0)


def build_leveraged_series(
    index_rows: list[tuple[date, float]],
    rate_dates: list[date],
    rate_map: dict[date, float],
    leverage: float,
    include_financing_cost: bool,
) -> list[tuple[date, float]]:
    synthetic: list[tuple[date, float]] = [(index_rows[0][0], 100.0)]
    for idx in range(1, len(index_rows)):
        prev_date, prev_close = index_rows[idx - 1]
        current_date, current_close = index_rows[idx]
        days = (current_date - prev_date).days
        index_return = current_close / prev_close - 1.0
        gross_multiplier = max(1e-12, 1.0 + leverage * index_return)
        if include_financing_cost:
            rate = get_latest_value(prev_date, rate_dates, rate_map)
            gross_multiplier *= interval_cost_multiplier(days, rate, leverage)
        synthetic.append((current_date, synthetic[-1][1] * gross_multiplier))
    return synthetic


def build_spliced_series(
    early_rows: list[tuple[date, float]],
    later_rows: list[tuple[date, float]],
    splice_date: date,
) -> list[tuple[date, float]]:
    early_map = dict(early_rows)
    later_start_price = next(price for row_date, price in later_rows if row_date == splice_date)
    scale = early_map[splice_date] / later_start_price
    return (
        [(row_date, price) for row_date, price in early_rows if row_date < splice_date]
        + [(row_date, price * scale) for row_date, price in later_rows]
    )


def rolling_sma(series: list[tuple[date, float]], window: int) -> list[float | None]:
    output: list[float | None] = []
    running_sum = 0.0
    values = [price for _, price in series]
    for idx, value in enumerate(values):
        running_sum += value
        if idx >= window:
            running_sum -= values[idx - window]
        output.append(running_sum / window if idx + 1 >= window else None)
    return output


def has_consecutive_signal(flags: list[bool], idx: int, count: int) -> bool:
    if count <= 0:
        raise ValueError("Signal confirmation count must be at least 1.")
    if idx < count - 1:
        return False
    return all(flags[idx - offset] for offset in range(count))


def calculate_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        drawdown = value / peak - 1.0
        if drawdown < worst:
            worst = drawdown
    return worst


def compute_summary_stats(
    name: str,
    equity_curve: list[tuple[date, float]],
    final_value: float,
    trades: int,
    time_in_market: float,
) -> MetricRow:
    start = equity_curve[0][0]
    end = equity_curve[-1][0]
    total_days = (end - start).days
    cagr = final_value ** (365.2425 / total_days) - 1.0
    values = [value for _, value in equity_curve]
    values.append(final_value)
    mdd = calculate_drawdown(values)
    calmar = cagr / abs(mdd) if mdd < 0 else float("inf")
    return MetricRow(name, final_value, cagr, mdd, calmar, trades, time_in_market)


def compute_calendar_year_returns(curve: list[tuple[date, float]]) -> list[dict[str, object]]:
    year_end: dict[int, tuple[date, float]] = {}
    year_first: dict[int, tuple[date, float]] = {}
    for current_date, current_value in curve:
        year_end[current_date.year] = (current_date, current_value)
        year_first.setdefault(current_date.year, (current_date, current_value))

    years = sorted(year_end)
    rows: list[dict[str, object]] = []
    previous_end_value: float | None = None
    for year in years:
        start_date, start_value = year_first[year]
        end_date, end_value = year_end[year]
        basis = previous_end_value if previous_end_value is not None else start_value
        annual_return = end_value / basis - 1.0 if basis > 0 else float("nan")
        rows.append(
            {
                "year": year,
                "start_date": start_date,
                "end_date": end_date,
                "return": annual_return,
                "is_partial": year == years[0] or year == years[-1],
            }
        )
        previous_end_value = end_value
    return rows


def compute_drawdown_episodes(strategy_name: str, curve: list[tuple[date, float]]) -> list[DrawdownEpisode]:
    peak_date, peak_value = curve[0]
    episode_peak_date, episode_peak_value = peak_date, peak_value
    trough_date, trough_value = peak_date, peak_value
    in_drawdown = False
    episodes: list[DrawdownEpisode] = []

    for current_date, current_value in curve[1:]:
        if current_value >= peak_value:
            if in_drawdown and trough_value < episode_peak_value:
                episodes.append(
                    DrawdownEpisode(
                        strategy_name,
                        0,
                        episode_peak_date,
                        trough_date,
                        current_date,
                        trough_value / episode_peak_value - 1.0,
                        (trough_date - episode_peak_date).days,
                        (current_date - episode_peak_date).days,
                        True,
                    )
                )
                in_drawdown = False
            peak_date, peak_value = current_date, current_value
            episode_peak_date, episode_peak_value = peak_date, peak_value
            trough_date, trough_value = current_date, current_value
            continue

        if not in_drawdown:
            in_drawdown = True
            trough_date, trough_value = current_date, current_value
        elif current_value < trough_value:
            trough_date, trough_value = current_date, current_value

    if in_drawdown and trough_value < episode_peak_value:
        episodes.append(
            DrawdownEpisode(
                strategy_name,
                0,
                episode_peak_date,
                trough_date,
                None,
                trough_value / episode_peak_value - 1.0,
                (trough_date - episode_peak_date).days,
                None,
                False,
            )
        )

    episodes.sort(key=lambda item: item.drawdown)
    ranked: list[DrawdownEpisode] = []
    for rank, item in enumerate(episodes, start=1):
        ranked.append(
            DrawdownEpisode(
                item.strategy,
                rank,
                item.peak_date,
                item.trough_date,
                item.recovery_date,
                item.drawdown,
                item.peak_to_trough_days,
                item.peak_to_recovery_days,
                item.recovered,
            )
        )
    return ranked


def simulate_buy_and_hold(series: list[tuple[date, float]]) -> tuple[MetricRow, list[tuple[date, float]]]:
    first_date, first_price = series[0]
    shares = 1.0 / ((1.0 + COMMISSION_RATE) * first_price)
    cost_basis = 1.0
    equity_curve = [(first_date, shares * first_price)]
    for current_date, current_price in series[1:]:
        equity_curve.append((current_date, shares * current_price))

    last_price = series[-1][1]
    gross_value = shares * last_price
    net_after_commission = gross_value * (1.0 - COMMISSION_RATE)
    realized_gain = net_after_commission - cost_basis
    final_value = net_after_commission - max(realized_gain, 0.0) * TAX_RATE
    metrics = compute_summary_stats("Buy and Hold", equity_curve, final_value, 2, 1.0)
    return metrics, equity_curve


def simulate_three_day_timing(
    series: list[tuple[date, float]],
    rate_dates: list[date],
    rate_map: dict[date, float],
    strategy_name: str,
) -> tuple[MetricRow, list[tuple[date, float]]]:
    return simulate_price_vs_sma_timing(
        series=series,
        rate_dates=rate_dates,
        rate_map=rate_map,
        strategy_name=strategy_name,
        sma_window=SMA_WINDOW,
        entry_confirm_days=ENTRY_CONFIRM_DAYS,
        exit_confirm_days=1,
    )


def simulate_price_vs_sma_timing(
    series: list[tuple[date, float]],
    rate_dates: list[date],
    rate_map: dict[date, float],
    strategy_name: str,
    sma_window: int,
    entry_confirm_days: int,
    exit_confirm_days: int,
) -> tuple[MetricRow, list[tuple[date, float]]]:
    if sma_window < 1:
        raise ValueError("sma_window must be at least 1.")
    if entry_confirm_days < 1 or exit_confirm_days < 1:
        raise ValueError("entry_confirm_days and exit_confirm_days must be at least 1.")

    sma = rolling_sma(series, sma_window)
    above = [value is not None and price > value for (_, price), value in zip(series, sma, strict=True)]
    below = [value is not None and price < value for (_, price), value in zip(series, sma, strict=True)]

    cash = 1.0
    shares = 0.0
    basis = 0.0
    in_asset = False
    trades = 0
    days_in_asset = 0
    realized_by_year: dict[int, float] = {}
    equity_curve: list[tuple[date, float]] = [(series[0][0], 1.0)]

    for idx in range(1, len(series)):
        prev_date, _ = series[idx - 1]
        current_date, current_price = series[idx]
        days = (current_date - prev_date).days

        if in_asset:
            days_in_asset += days
        else:
            rate = get_latest_value(prev_date, rate_dates, rate_map)
            cash *= interval_cash_multiplier(days, rate)

        if current_date.year != prev_date.year:
            tax = max(realized_by_year.get(prev_date.year, 0.0), 0.0) * TAX_RATE
            if tax > 0.0:
                if in_asset:
                    portfolio_value = shares * current_price
                    ratio = max((portfolio_value - tax) / portfolio_value, 0.0)
                    shares *= ratio
                    basis *= ratio
                else:
                    cash -= tax
            realized_by_year.setdefault(current_date.year, 0.0)

        can_exit = in_asset and has_consecutive_signal(below, idx, exit_confirm_days)
        if can_exit:
            gross_sale = shares * current_price
            net_sale = gross_sale * (1.0 - COMMISSION_RATE)
            realized = net_sale - basis
            realized_by_year[current_date.year] = realized_by_year.get(current_date.year, 0.0) + realized
            cash = net_sale
            shares = 0.0
            basis = 0.0
            in_asset = False
            trades += 1

        can_enter = not in_asset and has_consecutive_signal(above, idx, entry_confirm_days)
        if can_enter:
            gross_purchase = cash / (1.0 + COMMISSION_RATE)
            shares = gross_purchase / current_price
            basis = cash
            cash = 0.0
            in_asset = True
            trades += 1

        equity_curve.append((current_date, shares * current_price if in_asset else cash))

    last_date, last_price = series[-1]
    if in_asset:
        gross_sale = shares * last_price
        net_sale = gross_sale * (1.0 - COMMISSION_RATE)
        realized = net_sale - basis
        realized_by_year[last_date.year] = realized_by_year.get(last_date.year, 0.0) + realized
        cash = net_sale
        trades += 1

    final_tax = max(realized_by_year.get(last_date.year, 0.0), 0.0) * TAX_RATE
    final_value = cash - final_tax
    total_days = (series[-1][0] - series[0][0]).days
    time_in_market = days_in_asset / total_days if total_days > 0 else 0.0
    metrics = compute_summary_stats(strategy_name, equity_curve, final_value, trades, time_in_market)
    return metrics, equity_curve


def simulate_dual_sma_timing(
    series: list[tuple[date, float]],
    rate_dates: list[date],
    rate_map: dict[date, float],
    strategy_name: str,
    fast_window: int,
    slow_window: int,
    entry_confirm_days: int,
    exit_confirm_days: int,
) -> tuple[MetricRow, list[tuple[date, float]]]:
    if fast_window < 1 or slow_window < 1:
        raise ValueError("Moving average windows must be at least 1.")
    if fast_window >= slow_window:
        raise ValueError("fast_window must be smaller than slow_window.")
    if entry_confirm_days < 1 or exit_confirm_days < 1:
        raise ValueError("entry_confirm_days and exit_confirm_days must be at least 1.")

    fast_sma = rolling_sma(series, fast_window)
    slow_sma = rolling_sma(series, slow_window)
    bullish = [
        fast is not None and slow is not None and fast > slow
        for fast, slow in zip(fast_sma, slow_sma, strict=True)
    ]
    bearish = [
        fast is not None and slow is not None and fast < slow
        for fast, slow in zip(fast_sma, slow_sma, strict=True)
    ]

    cash = 1.0
    shares = 0.0
    basis = 0.0
    in_asset = False
    trades = 0
    days_in_asset = 0
    realized_by_year: dict[int, float] = {}
    equity_curve: list[tuple[date, float]] = [(series[0][0], 1.0)]

    for idx in range(1, len(series)):
        prev_date, _ = series[idx - 1]
        current_date, current_price = series[idx]
        days = (current_date - prev_date).days

        if in_asset:
            days_in_asset += days
        else:
            rate = get_latest_value(prev_date, rate_dates, rate_map)
            cash *= interval_cash_multiplier(days, rate)

        if current_date.year != prev_date.year:
            tax = max(realized_by_year.get(prev_date.year, 0.0), 0.0) * TAX_RATE
            if tax > 0.0:
                if in_asset:
                    portfolio_value = shares * current_price
                    ratio = max((portfolio_value - tax) / portfolio_value, 0.0)
                    shares *= ratio
                    basis *= ratio
                else:
                    cash -= tax
            realized_by_year.setdefault(current_date.year, 0.0)

        can_exit = in_asset and has_consecutive_signal(bearish, idx, exit_confirm_days)
        if can_exit:
            gross_sale = shares * current_price
            net_sale = gross_sale * (1.0 - COMMISSION_RATE)
            realized = net_sale - basis
            realized_by_year[current_date.year] = realized_by_year.get(current_date.year, 0.0) + realized
            cash = net_sale
            shares = 0.0
            basis = 0.0
            in_asset = False
            trades += 1

        can_enter = not in_asset and has_consecutive_signal(bullish, idx, entry_confirm_days)
        if can_enter:
            gross_purchase = cash / (1.0 + COMMISSION_RATE)
            shares = gross_purchase / current_price
            basis = cash
            cash = 0.0
            in_asset = True
            trades += 1

        equity_curve.append((current_date, shares * current_price if in_asset else cash))

    last_date, last_price = series[-1]
    if in_asset:
        gross_sale = shares * last_price
        net_sale = gross_sale * (1.0 - COMMISSION_RATE)
        realized = net_sale - basis
        realized_by_year[last_date.year] = realized_by_year.get(last_date.year, 0.0) + realized
        cash = net_sale
        trades += 1

    final_tax = max(realized_by_year.get(last_date.year, 0.0), 0.0) * TAX_RATE
    final_value = cash - final_tax
    total_days = (series[-1][0] - series[0][0]).days
    time_in_market = days_in_asset / total_days if total_days > 0 else 0.0
    metrics = compute_summary_stats(strategy_name, equity_curve, final_value, trades, time_in_market)
    return metrics, equity_curve


def simulate_staged_strategy(
    series: list[tuple[date, float]],
    rate_dates: list[date],
    rate_map: dict[date, float],
    proxy_dates: list[date],
    proxy_map: dict[date, float],
    strategy_name: str,
) -> dict[str, object]:
    sma = rolling_sma(series, SMA_WINDOW)
    above = [value is not None and price > value for (_, price), value in zip(series, sma, strict=True)]

    cash = 1.0
    asset_shares = 0.0
    asset_basis = 0.0
    proxy_shares = 0.0
    proxy_basis = 0.0
    in_asset = False
    entry_price = None
    triggered_thresholds: set[float] = set()
    trades = 0
    days_in_asset = 0
    realized_by_year: dict[int, float] = {}
    equity_curve = [(series[0][0], 1.0)]
    small_hits = 0
    large_hits = 0

    def move_sale_to_proxy(current_date: date, current_asset_price: float, current_proxy_price: float, sell_fraction: float) -> None:
        nonlocal asset_shares, asset_basis, proxy_shares, proxy_basis, trades
        if asset_shares <= 0.0:
            return
        sell_shares = asset_shares * sell_fraction
        basis_sold = asset_basis * sell_fraction
        gross_sale = sell_shares * current_asset_price
        net_sale = gross_sale * (1.0 - COMMISSION_RATE)
        realized_by_year[current_date.year] = realized_by_year.get(current_date.year, 0.0) + (net_sale - basis_sold)
        asset_shares -= sell_shares
        asset_basis -= basis_sold
        trades += 1
        proxy_cash = net_sale / (1.0 + COMMISSION_RATE)
        proxy_shares += proxy_cash / current_proxy_price
        proxy_basis += net_sale
        trades += 1

    for idx in range(1, len(series)):
        prev_date, _ = series[idx - 1]
        current_date, current_asset_price = series[idx]
        current_proxy_price = get_latest_value(current_date, proxy_dates, proxy_map)
        days = (current_date - prev_date).days

        if in_asset:
            days_in_asset += days
        else:
            rate = get_latest_value(prev_date, rate_dates, rate_map)
            cash *= interval_cash_multiplier(days, rate)

        if current_date.year != prev_date.year:
            tax = max(realized_by_year.get(prev_date.year, 0.0), 0.0) * TAX_RATE
            if tax > 0.0:
                asset_value = asset_shares * current_asset_price
                proxy_value = proxy_shares * current_proxy_price
                portfolio_value = cash + asset_value + proxy_value
                ratio = max((portfolio_value - tax) / portfolio_value, 0.0) if portfolio_value > 0 else 0.0
                cash *= ratio
                asset_shares *= ratio
                asset_basis *= ratio
                proxy_shares *= ratio
                proxy_basis *= ratio
            realized_by_year.setdefault(current_date.year, 0.0)

        if in_asset and sma[idx] is not None and current_asset_price < sma[idx]:
            gross_sale = asset_shares * current_asset_price
            net_sale = gross_sale * (1.0 - COMMISSION_RATE)
            realized_by_year[current_date.year] = realized_by_year.get(current_date.year, 0.0) + (net_sale - asset_basis)
            cash += net_sale
            asset_shares = 0.0
            asset_basis = 0.0
            trades += 1

            if proxy_shares > 0.0:
                gross_proxy_sale = proxy_shares * current_proxy_price
                net_proxy_sale = gross_proxy_sale * (1.0 - COMMISSION_RATE)
                realized_by_year[current_date.year] = realized_by_year.get(current_date.year, 0.0) + (net_proxy_sale - proxy_basis)
                cash += net_proxy_sale
                proxy_shares = 0.0
                proxy_basis = 0.0
                trades += 1

            in_asset = False
            entry_price = None
            triggered_thresholds.clear()

        can_enter = (
            not in_asset
            and idx >= ENTRY_CONFIRM_DAYS - 1
            and all(above[idx - offset] for offset in range(ENTRY_CONFIRM_DAYS))
        )
        if can_enter:
            gross_purchase = cash / (1.0 + COMMISSION_RATE)
            asset_shares = gross_purchase / current_asset_price
            asset_basis = cash
            cash = 0.0
            in_asset = True
            entry_price = current_asset_price
            triggered_thresholds.clear()
            trades += 1

        if in_asset and entry_price is not None and asset_shares > 0.0:
            gain_multiple = current_asset_price / entry_price
            thresholds_to_fire: list[tuple[float, float, str]] = []

            for threshold in SMALL_EXIT_THRESHOLDS:
                if gain_multiple >= threshold and threshold not in triggered_thresholds:
                    thresholds_to_fire.append((threshold, 0.10, "small"))

            if gain_multiple >= LARGE_EXIT_START:
                max_threshold = int(gain_multiple)
                for threshold_int in range(int(LARGE_EXIT_START), max_threshold + 1):
                    threshold = float(threshold_int)
                    if threshold not in triggered_thresholds:
                        thresholds_to_fire.append((threshold, 0.50, "large"))

            thresholds_to_fire.sort(key=lambda item: item[0])
            for threshold, sell_fraction, bucket in thresholds_to_fire:
                move_sale_to_proxy(current_date, current_asset_price, current_proxy_price, sell_fraction)
                triggered_thresholds.add(threshold)
                if bucket == "small":
                    small_hits += 1
                else:
                    large_hits += 1

        equity_value = cash + (asset_shares * current_asset_price) + (proxy_shares * current_proxy_price)
        equity_curve.append((current_date, equity_value))

    last_date, last_asset_price = series[-1]
    last_proxy_price = get_latest_value(last_date, proxy_dates, proxy_map)

    if asset_shares > 0.0:
        gross_sale = asset_shares * last_asset_price
        net_sale = gross_sale * (1.0 - COMMISSION_RATE)
        realized_by_year[last_date.year] = realized_by_year.get(last_date.year, 0.0) + (net_sale - asset_basis)
        cash += net_sale
        trades += 1

    if proxy_shares > 0.0:
        gross_sale = proxy_shares * last_proxy_price
        net_sale = gross_sale * (1.0 - COMMISSION_RATE)
        realized_by_year[last_date.year] = realized_by_year.get(last_date.year, 0.0) + (net_sale - proxy_basis)
        cash += net_sale
        trades += 1

    final_tax = max(realized_by_year.get(last_date.year, 0.0), 0.0) * TAX_RATE
    final_value = cash - final_tax
    total_days = (series[-1][0] - series[0][0]).days
    time_in_market = days_in_asset / total_days if total_days > 0 else 0.0

    metrics = compute_summary_stats(strategy_name, equity_curve, final_value, trades, time_in_market)
    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "annual_rows": compute_calendar_year_returns(equity_curve),
        "drawdowns": compute_drawdown_episodes(strategy_name, equity_curve),
        "small_hits": small_hits,
        "large_hits": large_hits,
    }


def write_metrics_csv(path: Path, rows: list[MetricRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy", "final_multiple", "cagr", "mdd", "calmar", "trades", "time_in_market"])
        for row in rows:
            writer.writerow(
                [
                    row.name,
                    f"{row.final_value:.4f}",
                    f"{row.cagr:.6f}",
                    f"{row.mdd:.6f}",
                    f"{row.calmar:.3f}",
                    row.trades,
                    f"{row.time_in_market:.4f}",
                ]
            )


def write_annual_returns_csv(path: Path, annual_by_strategy: dict[str, list[dict[str, object]]]) -> None:
    years = [row["year"] for row in next(iter(annual_by_strategy.values()))]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["year", "start_date", "end_date", "period_type", *annual_by_strategy.keys()])
        for idx, year in enumerate(years):
            sample = next(iter(annual_by_strategy.values()))[idx]
            writer.writerow(
                [
                    year,
                    sample["start_date"].isoformat(),
                    sample["end_date"].isoformat(),
                    "partial" if sample["is_partial"] else "full",
                    *[
                        f"{annual_by_strategy[name][idx]['return']:.6f}"
                        for name in annual_by_strategy
                    ],
                ]
            )


def write_drawdowns_csv(path: Path, drawdowns_by_strategy: dict[str, list[DrawdownEpisode]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "strategy",
                "rank",
                "peak_date",
                "trough_date",
                "recovery_date",
                "drawdown",
                "peak_to_trough_days",
                "peak_to_recovery_days",
                "recovered",
            ]
        )
        for strategy, episodes in drawdowns_by_strategy.items():
            for episode in episodes:
                writer.writerow(
                    [
                        strategy,
                        episode.rank,
                        episode.peak_date.isoformat(),
                        episode.trough_date.isoformat(),
                        episode.recovery_date.isoformat() if episode.recovery_date else "",
                        f"{episode.drawdown:.6f}",
                        episode.peak_to_trough_days,
                        episode.peak_to_recovery_days if episode.peak_to_recovery_days is not None else "",
                        int(episode.recovered),
                    ]
                )


def write_equity_curves_csv(path: Path, curves_by_strategy: dict[str, list[tuple[date, float]]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy", "date", "equity"])
        for strategy, curve in curves_by_strategy.items():
            for row_date, value in curve:
                writer.writerow([strategy, row_date.isoformat(), f"{value:.6f}"])


def write_rows_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("No rows to write.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
