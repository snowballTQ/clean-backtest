from __future__ import annotations

import argparse
import json
from datetime import datetime

import backtest as bt


VALID_BASE_SERIES = {"ndx", "spx", "composite_splice"}


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


def parse_name_list(value: str, valid_choices: set[str]) -> list[str]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("Expected a comma-separated list of names.")
    invalid = [item for item in parts if item not in valid_choices]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Unsupported names: {', '.join(invalid)}. Valid choices: {', '.join(sorted(valid_choices))}."
        )
    deduped: list[str] = []
    for item in parts:
        if item not in deduped:
            deduped.append(item)
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a configurable backtest toolbox with multiple base series, leverage settings, and timing rules.",
    )
    parser.add_argument("--start-date", default=bt.DEFAULT_START_DATE.isoformat(), help="Backtest start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", default=bt.DEFAULT_END_DATE.isoformat(), help="Backtest end date in YYYY-MM-DD format.")
    parser.add_argument(
        "--base-series",
        default="ndx",
        help="Comma-separated base series such as ndx, spx, composite_splice.",
    )
    parser.add_argument("--leverages", default="2,3", help="Comma-separated leverage values such as 2,3.")
    parser.add_argument(
        "--include-base-series",
        dest="include_base_series",
        action="store_true",
        default=True,
        help="Include 1x base-series strategies in the output.",
    )
    parser.add_argument(
        "--skip-base-series",
        dest="include_base_series",
        action="store_false",
        help="Skip 1x base-series strategies.",
    )
    parser.add_argument("--include-zero-cost", action="store_true", help="Include zero-cost leveraged series.")
    parser.add_argument("--skip-cost-adjusted", action="store_true", help="Skip cost-adjusted leveraged series.")
    parser.add_argument("--skip-buyhold", action="store_true", help="Skip buy-and-hold strategies.")
    parser.add_argument("--skip-price-sma", action="store_true", help="Skip price-vs-SMA timing strategies.")
    parser.add_argument("--skip-dual-sma", action="store_true", help="Skip fast/slow SMA crossover strategies.")
    parser.add_argument("--skip-timing", action="store_true", help="Backward-compatible alias for --skip-price-sma.")
    parser.add_argument("--price-sma-window", type=int, default=200, help="Moving average window length for the price-vs-SMA strategy.")
    parser.add_argument("--price-entry-confirm-days", type=int, default=3, help="Consecutive closes above the SMA before entry.")
    parser.add_argument("--price-exit-confirm-days", type=int, default=1, help="Consecutive closes below the SMA before exit.")
    parser.add_argument("--fast-sma-window", type=int, default=50, help="Fast moving average window for the crossover strategy.")
    parser.add_argument("--slow-sma-window", type=int, default=200, help="Slow moving average window for the crossover strategy.")
    parser.add_argument("--cross-entry-confirm-days", type=int, default=1, help="Consecutive fast-over-slow signals before entry.")
    parser.add_argument("--cross-exit-confirm-days", type=int, default=1, help="Consecutive fast-under-slow signals before exit.")
    parser.add_argument("--commission-rate", type=float, default=bt.COMMISSION_RATE, help="Commission per side as a decimal.")
    parser.add_argument("--tax-rate", type=float, default=bt.TAX_RATE, help="Tax rate on net realized gains by calendar year.")
    parser.add_argument("--expense-ratio", type=float, default=bt.EXPENSE_RATIO, help="Annual expense ratio as a decimal.")
    parser.add_argument("--borrow-spread", type=float, default=bt.BORROW_SPREAD, help="Borrow spread added to DFF, in percentage points.")
    parser.add_argument("--output-name", default="custom_analysis", help="Name of the output folder created under the output root.")
    return parser


def apply_runtime_settings(args) -> None:
    bt.COMMISSION_RATE = args.commission_rate
    bt.TAX_RATE = args.tax_rate
    bt.EXPENSE_RATIO = args.expense_ratio
    bt.BORROW_SPREAD = args.borrow_spread


def add_strategy_result(
    metric_rows: list[bt.MetricRow],
    annual_by_strategy: dict[str, list[dict[str, object]]],
    drawdowns_by_strategy: dict[str, list[bt.DrawdownEpisode]],
    curves_by_strategy: dict[str, list[tuple[object, float]]],
    metrics: bt.MetricRow,
    curve: list[tuple[object, float]],
) -> None:
    metric_rows.append(metrics)
    annual_by_strategy[metrics.name] = bt.compute_calendar_year_returns(curve)
    drawdowns_by_strategy[metrics.name] = bt.compute_drawdown_episodes(metrics.name, curve)
    curves_by_strategy[metrics.name] = curve


def add_buyhold_and_timing_results(
    *,
    series: list[tuple[object, float]],
    rate_dates: list[object],
    rate_map: dict[object, float],
    label_prefix: str,
    include_buyhold: bool,
    include_price_sma: bool,
    include_dual_sma: bool,
    price_sma_window: int,
    price_entry_confirm_days: int,
    price_exit_confirm_days: int,
    fast_sma_window: int,
    slow_sma_window: int,
    cross_entry_confirm_days: int,
    cross_exit_confirm_days: int,
    metric_rows: list[bt.MetricRow],
    annual_by_strategy: dict[str, list[dict[str, object]]],
    drawdowns_by_strategy: dict[str, list[bt.DrawdownEpisode]],
    curves_by_strategy: dict[str, list[tuple[object, float]]],
) -> None:
    if include_buyhold:
        metrics, curve = bt.simulate_buy_and_hold(series)
        metrics.name = f"Buy and Hold | {label_prefix}"
        add_strategy_result(metric_rows, annual_by_strategy, drawdowns_by_strategy, curves_by_strategy, metrics, curve)

    if include_price_sma:
        metrics, curve = bt.simulate_price_vs_sma_timing(
            series=series,
            rate_dates=rate_dates,
            rate_map=rate_map,
            strategy_name=(
                f"Price vs SMA | {label_prefix} | "
                f"sma={price_sma_window} | in={price_entry_confirm_days} | out={price_exit_confirm_days}"
            ),
            sma_window=price_sma_window,
            entry_confirm_days=price_entry_confirm_days,
            exit_confirm_days=price_exit_confirm_days,
        )
        add_strategy_result(metric_rows, annual_by_strategy, drawdowns_by_strategy, curves_by_strategy, metrics, curve)

    if include_dual_sma:
        metrics, curve = bt.simulate_dual_sma_timing(
            series=series,
            rate_dates=rate_dates,
            rate_map=rate_map,
            strategy_name=(
                f"Dual SMA | {label_prefix} | "
                f"fast={fast_sma_window} | slow={slow_sma_window} | "
                f"in={cross_entry_confirm_days} | out={cross_exit_confirm_days}"
            ),
            fast_window=fast_sma_window,
            slow_window=slow_sma_window,
            entry_confirm_days=cross_entry_confirm_days,
            exit_confirm_days=cross_exit_confirm_days,
        )
        add_strategy_result(metric_rows, annual_by_strategy, drawdowns_by_strategy, curves_by_strategy, metrics, curve)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if start_date >= end_date:
        raise ValueError("start-date must be earlier than end-date.")

    base_series_names = parse_name_list(args.base_series, VALID_BASE_SERIES)
    leverage_values = parse_float_list(args.leverages)
    include_buyhold = not args.skip_buyhold
    include_price_sma = not (args.skip_price_sma or args.skip_timing)
    include_dual_sma = not args.skip_dual_sma
    include_cost_adjusted = not args.skip_cost_adjusted
    include_zero_cost = args.include_zero_cost

    if not include_zero_cost and not include_cost_adjusted:
        raise ValueError("At least one of zero-cost or cost-adjusted series must be enabled.")
    if not include_buyhold and not include_price_sma and not include_dual_sma:
        raise ValueError("At least one strategy family must be enabled.")

    apply_runtime_settings(args)

    rate_rows = bt.load_rate_rows(None, end_date)
    rate_dates = [row_date for row_date, _ in rate_rows]
    rate_map = dict(rate_rows)

    output_dir = bt.ensure_output_dir(args.output_name)
    metrics_path = output_dir / "metrics.csv"
    annual_path = output_dir / "annual_returns.csv"
    drawdowns_path = output_dir / "drawdowns.csv"
    curves_path = output_dir / "equity_curves.csv"
    config_path = output_dir / "config.json"

    metric_rows: list[bt.MetricRow] = []
    annual_by_strategy: dict[str, list[dict[str, object]]] = {}
    drawdowns_by_strategy: dict[str, list[bt.DrawdownEpisode]] = {}
    curves_by_strategy: dict[str, list[tuple[object, float]]] = {}

    for base_series_name in base_series_names:
        base_rows = bt.resolve_base_rows(base_series_name, start_date, end_date)
        normalized_base = bt.normalize_series(base_rows)

        if args.include_base_series:
            add_buyhold_and_timing_results(
                series=normalized_base,
                rate_dates=rate_dates,
                rate_map=rate_map,
                label_prefix=f"1.00x | base={base_series_name}",
                include_buyhold=include_buyhold,
                include_price_sma=include_price_sma,
                include_dual_sma=include_dual_sma,
                price_sma_window=args.price_sma_window,
                price_entry_confirm_days=args.price_entry_confirm_days,
                price_exit_confirm_days=args.price_exit_confirm_days,
                fast_sma_window=args.fast_sma_window,
                slow_sma_window=args.slow_sma_window,
                cross_entry_confirm_days=args.cross_entry_confirm_days,
                cross_exit_confirm_days=args.cross_exit_confirm_days,
                metric_rows=metric_rows,
                annual_by_strategy=annual_by_strategy,
                drawdowns_by_strategy=drawdowns_by_strategy,
                curves_by_strategy=curves_by_strategy,
            )

        for leverage in leverage_values:
            if leverage <= 1.0:
                continue

            if include_zero_cost:
                zero_series = bt.build_leveraged_series(
                    base_rows,
                    rate_dates,
                    rate_map,
                    leverage=leverage,
                    include_financing_cost=False,
                )
                add_buyhold_and_timing_results(
                    series=zero_series,
                    rate_dates=rate_dates,
                    rate_map=rate_map,
                    label_prefix=f"{leverage:.2f}x | zero cost | base={base_series_name}",
                    include_buyhold=include_buyhold,
                    include_price_sma=include_price_sma,
                    include_dual_sma=include_dual_sma,
                    price_sma_window=args.price_sma_window,
                    price_entry_confirm_days=args.price_entry_confirm_days,
                    price_exit_confirm_days=args.price_exit_confirm_days,
                    fast_sma_window=args.fast_sma_window,
                    slow_sma_window=args.slow_sma_window,
                    cross_entry_confirm_days=args.cross_entry_confirm_days,
                    cross_exit_confirm_days=args.cross_exit_confirm_days,
                    metric_rows=metric_rows,
                    annual_by_strategy=annual_by_strategy,
                    drawdowns_by_strategy=drawdowns_by_strategy,
                    curves_by_strategy=curves_by_strategy,
                )

            if include_cost_adjusted:
                cost_series = bt.build_leveraged_series(
                    base_rows,
                    rate_dates,
                    rate_map,
                    leverage=leverage,
                    include_financing_cost=True,
                )
                add_buyhold_and_timing_results(
                    series=cost_series,
                    rate_dates=rate_dates,
                    rate_map=rate_map,
                    label_prefix=f"{leverage:.2f}x | cost-adjusted | base={base_series_name}",
                    include_buyhold=include_buyhold,
                    include_price_sma=include_price_sma,
                    include_dual_sma=include_dual_sma,
                    price_sma_window=args.price_sma_window,
                    price_entry_confirm_days=args.price_entry_confirm_days,
                    price_exit_confirm_days=args.price_exit_confirm_days,
                    fast_sma_window=args.fast_sma_window,
                    slow_sma_window=args.slow_sma_window,
                    cross_entry_confirm_days=args.cross_entry_confirm_days,
                    cross_exit_confirm_days=args.cross_exit_confirm_days,
                    metric_rows=metric_rows,
                    annual_by_strategy=annual_by_strategy,
                    drawdowns_by_strategy=drawdowns_by_strategy,
                    curves_by_strategy=curves_by_strategy,
                )

    if not metric_rows:
        raise ValueError("No strategies were selected. Adjust the options and try again.")

    bt.write_metrics_csv(metrics_path, metric_rows)
    bt.write_annual_returns_csv(annual_path, annual_by_strategy)
    bt.write_drawdowns_csv(drawdowns_path, drawdowns_by_strategy)
    bt.write_equity_curves_csv(curves_path, curves_by_strategy)

    config = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "base_series": base_series_names,
        "leverages": leverage_values,
        "include_base_series": args.include_base_series,
        "include_zero_cost": include_zero_cost,
        "include_cost_adjusted": include_cost_adjusted,
        "include_buyhold": include_buyhold,
        "include_price_sma": include_price_sma,
        "include_dual_sma": include_dual_sma,
        "price_sma_window": args.price_sma_window,
        "price_entry_confirm_days": args.price_entry_confirm_days,
        "price_exit_confirm_days": args.price_exit_confirm_days,
        "fast_sma_window": args.fast_sma_window,
        "slow_sma_window": args.slow_sma_window,
        "cross_entry_confirm_days": args.cross_entry_confirm_days,
        "cross_exit_confirm_days": args.cross_exit_confirm_days,
        "commission_rate": bt.COMMISSION_RATE,
        "tax_rate": bt.TAX_RATE,
        "expense_ratio": bt.EXPENSE_RATIO,
        "borrow_spread": bt.BORROW_SPREAD,
        "output_directory": str(output_dir),
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    print(f"wrote {metrics_path}")
    print(f"wrote {annual_path}")
    print(f"wrote {drawdowns_path}")
    print(f"wrote {curves_path}")
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
