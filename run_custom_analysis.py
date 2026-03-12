from __future__ import annotations

import argparse
import json
from datetime import datetime

import backtest as bt


def parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_float_list(value: str) -> list[float]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("Expected a comma-separated list of numbers.")
    try:
        return [float(item) for item in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run configurable backtests with custom date ranges, cost settings, and strategy options.",
    )
    parser.add_argument("--start-date", default=bt.DEFAULT_START_DATE.isoformat(), help="Backtest start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", default=bt.DEFAULT_END_DATE.isoformat(), help="Backtest end date in YYYY-MM-DD format.")
    parser.add_argument("--base-series", choices=["ndx", "composite_splice"], default="ndx", help="Underlying index history to use.")
    parser.add_argument("--leverages", default="2,3", help="Comma-separated leverage values such as 1,2,3.")
    parser.add_argument("--include-zero-cost", action="store_true", help="Include zero-cost leveraged series.")
    parser.add_argument("--skip-cost-adjusted", action="store_true", help="Skip cost-adjusted leveraged series.")
    parser.add_argument("--skip-buyhold", action="store_true", help="Skip buy-and-hold strategies.")
    parser.add_argument("--skip-timing", action="store_true", help="Skip moving-average timing strategies.")
    parser.add_argument("--include-staged", action="store_true", help="Include staged exit strategies.")
    parser.add_argument("--sma-window", type=int, default=bt.SMA_WINDOW, help="Moving average window length.")
    parser.add_argument("--entry-confirm-days", type=int, default=bt.ENTRY_CONFIRM_DAYS, help="Number of consecutive closes above the moving average before entry.")
    parser.add_argument("--commission-rate", type=float, default=bt.COMMISSION_RATE, help="Commission per side as a decimal.")
    parser.add_argument("--tax-rate", type=float, default=bt.TAX_RATE, help="Tax rate on net realized gains by calendar year.")
    parser.add_argument("--expense-ratio", type=float, default=bt.EXPENSE_RATIO, help="Annual expense ratio as a decimal.")
    parser.add_argument("--borrow-spread", type=float, default=bt.BORROW_SPREAD, help="Borrow spread added to DFF, in percentage points.")
    parser.add_argument("--small-exit-thresholds", default="1.10,1.25,1.50", help="Comma-separated thresholds for partial exits.")
    parser.add_argument("--large-exit-start", type=float, default=bt.LARGE_EXIT_START, help="Starting threshold for large staged exits.")
    parser.add_argument("--output-name", default="custom_analysis", help="Name of the output folder created under the output root.")
    return parser


def apply_runtime_settings(args) -> None:
    bt.COMMISSION_RATE = args.commission_rate
    bt.TAX_RATE = args.tax_rate
    bt.EXPENSE_RATIO = args.expense_ratio
    bt.BORROW_SPREAD = args.borrow_spread
    bt.SMA_WINDOW = args.sma_window
    bt.ENTRY_CONFIRM_DAYS = args.entry_confirm_days
    bt.SMALL_EXIT_THRESHOLDS = parse_float_list(args.small_exit_thresholds)
    bt.LARGE_EXIT_START = args.large_exit_start


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if start_date >= end_date:
        raise ValueError("start-date must be earlier than end-date.")

    apply_runtime_settings(args)
    leverage_values = parse_float_list(args.leverages)

    index_rows = bt.load_index_rows(start_date, end_date)
    rate_rows = bt.load_rate_rows(None, end_date)
    rate_dates = [row_date for row_date, _ in rate_rows]
    rate_map = dict(rate_rows)
    proxy_rows = bt.load_proxy_rows(start_date, end_date)
    proxy_dates = [row_date for row_date, _ in proxy_rows]
    proxy_map = dict(proxy_rows)

    if args.base_series == "composite_splice":
        composite_rows = bt.load_composite_rows(None, end_date)
        base_rows = bt.build_spliced_series(composite_rows, index_rows, start_date)
    else:
        base_rows = index_rows

    include_cost_adjusted = not args.skip_cost_adjusted
    include_zero_cost = args.include_zero_cost
    if not include_zero_cost and not include_cost_adjusted:
        raise ValueError("At least one of zero-cost or cost-adjusted series must be enabled.")

    output_dir = bt.ensure_output_dir(args.output_name)
    metrics_path = output_dir / "metrics.csv"
    annual_path = output_dir / "annual_returns.csv"
    drawdowns_path = output_dir / "drawdowns.csv"
    config_path = output_dir / "config.json"

    metric_rows = []
    annual_by_strategy = {}
    drawdowns_by_strategy = {}

    if 1.0 in leverage_values and not args.skip_buyhold:
        normalized_base = [(row_date, price / base_rows[0][1]) for row_date, price in base_rows]
        ndx_metrics, ndx_curve = bt.simulate_buy_and_hold(normalized_base)
        ndx_metrics.name = f"Index Buy and Hold | base={args.base_series}"
        metric_rows.append(ndx_metrics)
        annual_by_strategy[ndx_metrics.name] = bt.compute_calendar_year_returns(ndx_curve)
        drawdowns_by_strategy[ndx_metrics.name] = bt.compute_drawdown_episodes(ndx_metrics.name, ndx_curve)

    for leverage in leverage_values:
        if leverage == 1.0:
            continue

        if include_zero_cost:
            zero_series = bt.build_leveraged_series(base_rows, rate_dates, rate_map, leverage=leverage, include_financing_cost=False)
            if not args.skip_buyhold:
                metrics, curve = bt.simulate_buy_and_hold(zero_series)
                metrics.name = f"Buy and Hold | {leverage:.2f}x | zero cost | base={args.base_series}"
                metric_rows.append(metrics)
                annual_by_strategy[metrics.name] = bt.compute_calendar_year_returns(curve)
                drawdowns_by_strategy[metrics.name] = bt.compute_drawdown_episodes(metrics.name, curve)
            if not args.skip_timing:
                metrics, curve = bt.simulate_three_day_timing(
                    zero_series,
                    rate_dates,
                    rate_map,
                    strategy_name=f"Timing | {leverage:.2f}x | zero cost | base={args.base_series}",
                )
                metric_rows.append(metrics)
                annual_by_strategy[metrics.name] = bt.compute_calendar_year_returns(curve)
                drawdowns_by_strategy[metrics.name] = bt.compute_drawdown_episodes(metrics.name, curve)
            if args.include_staged:
                result = bt.simulate_staged_strategy(
                    zero_series,
                    rate_dates,
                    rate_map,
                    proxy_dates,
                    proxy_map,
                    strategy_name=f"Staged | {leverage:.2f}x | zero cost | base={args.base_series}",
                )
                metric_rows.append(result["metrics"])
                annual_by_strategy[result["metrics"].name] = result["annual_rows"]
                drawdowns_by_strategy[result["metrics"].name] = result["drawdowns"]

        if include_cost_adjusted:
            cost_series = bt.build_leveraged_series(base_rows, rate_dates, rate_map, leverage=leverage, include_financing_cost=True)
            if not args.skip_buyhold:
                metrics, curve = bt.simulate_buy_and_hold(cost_series)
                metrics.name = f"Buy and Hold | {leverage:.2f}x | cost-adjusted | base={args.base_series}"
                metric_rows.append(metrics)
                annual_by_strategy[metrics.name] = bt.compute_calendar_year_returns(curve)
                drawdowns_by_strategy[metrics.name] = bt.compute_drawdown_episodes(metrics.name, curve)
            if not args.skip_timing:
                metrics, curve = bt.simulate_three_day_timing(
                    cost_series,
                    rate_dates,
                    rate_map,
                    strategy_name=f"Timing | {leverage:.2f}x | cost-adjusted | base={args.base_series}",
                )
                metric_rows.append(metrics)
                annual_by_strategy[metrics.name] = bt.compute_calendar_year_returns(curve)
                drawdowns_by_strategy[metrics.name] = bt.compute_drawdown_episodes(metrics.name, curve)
            if args.include_staged:
                result = bt.simulate_staged_strategy(
                    cost_series,
                    rate_dates,
                    rate_map,
                    proxy_dates,
                    proxy_map,
                    strategy_name=f"Staged | {leverage:.2f}x | cost-adjusted | base={args.base_series}",
                )
                metric_rows.append(result["metrics"])
                annual_by_strategy[result["metrics"].name] = result["annual_rows"]
                drawdowns_by_strategy[result["metrics"].name] = result["drawdowns"]

    if not metric_rows:
        raise ValueError("No strategies were selected. Adjust the flags and try again.")

    bt.write_metrics_csv(metrics_path, metric_rows)
    bt.write_annual_returns_csv(annual_path, annual_by_strategy)
    bt.write_drawdowns_csv(drawdowns_path, drawdowns_by_strategy)

    config = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "base_series": args.base_series,
        "leverages": leverage_values,
        "include_zero_cost": include_zero_cost,
        "include_cost_adjusted": include_cost_adjusted,
        "include_buyhold": not args.skip_buyhold,
        "include_timing": not args.skip_timing,
        "include_staged": args.include_staged,
        "sma_window": bt.SMA_WINDOW,
        "entry_confirm_days": bt.ENTRY_CONFIRM_DAYS,
        "commission_rate": bt.COMMISSION_RATE,
        "tax_rate": bt.TAX_RATE,
        "expense_ratio": bt.EXPENSE_RATIO,
        "borrow_spread": bt.BORROW_SPREAD,
        "small_exit_thresholds": bt.SMALL_EXIT_THRESHOLDS,
        "large_exit_start": bt.LARGE_EXIT_START,
        "output_directory": str(output_dir),
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    print(f"wrote {metrics_path}")
    print(f"wrote {annual_path}")
    print(f"wrote {drawdowns_path}")
    print(f"wrote {config_path}")
    for row in metric_rows:
        print(
            f"{row.name}: "
            f"final={row.final_value:.4f}, "
            f"CAGR={row.cagr:.4%}, "
            f"MDD={row.mdd:.4%}, "
            f"Calmar={row.calmar:.3f}, "
            f"trades={row.trades}, "
            f"time_in_market={row.time_in_market:.2%}"
        )


if __name__ == "__main__":
    main()
