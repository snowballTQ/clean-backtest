from __future__ import annotations

from backtest import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    build_leveraged_series,
    compute_calendar_year_returns,
    compute_drawdown_episodes,
    ensure_output_dir,
    load_index_rows,
    load_rate_rows,
    simulate_buy_and_hold,
    simulate_three_day_timing,
    write_annual_returns_csv,
    write_drawdowns_csv,
    write_metrics_csv,
)


def main() -> None:
    output_dir = ensure_output_dir("core_analysis")
    metrics_path = output_dir / "metrics.csv"
    annual_path = output_dir / "annual_returns.csv"
    drawdowns_path = output_dir / "drawdowns.csv"

    index_rows = load_index_rows(DEFAULT_START_DATE, DEFAULT_END_DATE)
    rate_rows = load_rate_rows(None, DEFAULT_END_DATE)
    rate_dates = [row_date for row_date, _ in rate_rows]
    rate_map = dict(rate_rows)

    normalized_index = [(row_date, price / index_rows[0][1]) for row_date, price in index_rows]
    leveraged_2x_zero = build_leveraged_series(index_rows, rate_dates, rate_map, leverage=2.0, include_financing_cost=False)
    leveraged_2x_cost = build_leveraged_series(index_rows, rate_dates, rate_map, leverage=2.0, include_financing_cost=True)
    leveraged_3x_zero = build_leveraged_series(index_rows, rate_dates, rate_map, leverage=3.0, include_financing_cost=False)
    leveraged_3x_cost = build_leveraged_series(index_rows, rate_dates, rate_map, leverage=3.0, include_financing_cost=True)

    ndx_metrics, ndx_curve = simulate_buy_and_hold(normalized_index)
    ndx_metrics.name = "NDX Buy and Hold"

    two_x_zero_metrics, two_x_zero_curve = simulate_buy_and_hold(leveraged_2x_zero)
    two_x_zero_metrics.name = "Leveraged 2x Buy and Hold (zero cost)"

    two_x_cost_metrics, two_x_cost_curve = simulate_buy_and_hold(leveraged_2x_cost)
    two_x_cost_metrics.name = "Leveraged 2x Buy and Hold (cost-adjusted)"

    three_x_zero_metrics, three_x_zero_curve = simulate_buy_and_hold(leveraged_3x_zero)
    three_x_zero_metrics.name = "Leveraged 3x Buy and Hold (zero cost)"

    three_x_cost_metrics, three_x_cost_curve = simulate_buy_and_hold(leveraged_3x_cost)
    three_x_cost_metrics.name = "Leveraged 3x Buy and Hold (cost-adjusted)"

    timing_zero_metrics, timing_zero_curve = simulate_three_day_timing(
        leveraged_3x_zero,
        rate_dates,
        rate_map,
        strategy_name="Three-Day SMA Timing (zero cost, 3x)",
    )
    timing_cost_metrics, timing_cost_curve = simulate_three_day_timing(
        leveraged_3x_cost,
        rate_dates,
        rate_map,
        strategy_name="Three-Day SMA Timing (cost-adjusted, 3x)",
    )

    metric_rows = [
        ndx_metrics,
        two_x_zero_metrics,
        two_x_cost_metrics,
        three_x_zero_metrics,
        three_x_cost_metrics,
        timing_zero_metrics,
        timing_cost_metrics,
    ]
    annual_by_strategy = {
        ndx_metrics.name: compute_calendar_year_returns(ndx_curve),
        two_x_zero_metrics.name: compute_calendar_year_returns(two_x_zero_curve),
        two_x_cost_metrics.name: compute_calendar_year_returns(two_x_cost_curve),
        three_x_zero_metrics.name: compute_calendar_year_returns(three_x_zero_curve),
        three_x_cost_metrics.name: compute_calendar_year_returns(three_x_cost_curve),
        timing_zero_metrics.name: compute_calendar_year_returns(timing_zero_curve),
        timing_cost_metrics.name: compute_calendar_year_returns(timing_cost_curve),
    }
    drawdowns_by_strategy = {
        ndx_metrics.name: compute_drawdown_episodes(ndx_metrics.name, ndx_curve),
        two_x_zero_metrics.name: compute_drawdown_episodes(two_x_zero_metrics.name, two_x_zero_curve),
        two_x_cost_metrics.name: compute_drawdown_episodes(two_x_cost_metrics.name, two_x_cost_curve),
        three_x_zero_metrics.name: compute_drawdown_episodes(three_x_zero_metrics.name, three_x_zero_curve),
        three_x_cost_metrics.name: compute_drawdown_episodes(three_x_cost_metrics.name, three_x_cost_curve),
        timing_zero_metrics.name: compute_drawdown_episodes(timing_zero_metrics.name, timing_zero_curve),
        timing_cost_metrics.name: compute_drawdown_episodes(timing_cost_metrics.name, timing_cost_curve),
    }

    write_metrics_csv(metrics_path, metric_rows)
    write_annual_returns_csv(annual_path, annual_by_strategy)
    write_drawdowns_csv(drawdowns_path, drawdowns_by_strategy)

    print(f"wrote {metrics_path}")
    print(f"wrote {annual_path}")
    print(f"wrote {drawdowns_path}")
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
