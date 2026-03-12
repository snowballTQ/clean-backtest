from __future__ import annotations

import statistics

from backtest import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    build_leveraged_series,
    build_spliced_series,
    ensure_output_dir,
    load_composite_rows,
    load_index_rows,
    load_proxy_rows,
    load_rate_rows,
    simulate_staged_strategy,
    write_rows_csv,
)


def summarize_variant(strategy_name: str, result: dict[str, object]) -> dict[str, object]:
    metrics = result["metrics"]
    annual_rows = result["annual_rows"]
    full_year_rows = [row for row in annual_rows if not row["is_partial"]]
    annual_returns = [row["return"] for row in full_year_rows]
    worst_year = min(full_year_rows, key=lambda row: row["return"])
    best_year = max(full_year_rows, key=lambda row: row["return"])
    top_drawdown = result["drawdowns"][0]

    return {
        "strategy": strategy_name,
        "final_multiple": round(metrics.final_value, 6),
        "cagr": round(metrics.cagr, 6),
        "mdd": round(metrics.mdd, 6),
        "calmar": round(metrics.calmar, 6),
        "trades": metrics.trades,
        "time_in_market": round(metrics.time_in_market, 6),
        "positive_years": sum(value > 0 for value in annual_returns),
        "negative_years": sum(value < 0 for value in annual_returns),
        "median_annual_return": round(statistics.median(annual_returns), 6),
        "worst_year": worst_year["year"],
        "worst_return": round(worst_year["return"], 6),
        "best_year": best_year["year"],
        "best_return": round(best_year["return"], 6),
        "peak_date": top_drawdown.peak_date.isoformat(),
        "trough_date": top_drawdown.trough_date.isoformat(),
        "recovery_date": top_drawdown.recovery_date.isoformat() if top_drawdown.recovery_date else "open",
        "peak_to_trough_days": top_drawdown.peak_to_trough_days,
        "peak_to_recovery_days": top_drawdown.peak_to_recovery_days if top_drawdown.peak_to_recovery_days is not None else "open",
        "small_exit_hits": result["small_hits"],
        "large_exit_hits": result["large_hits"],
    }


def main() -> None:
    output_dir = ensure_output_dir("staged_analysis")
    summary_path = output_dir / "summary.csv"
    annual_path = output_dir / "annual_returns.csv"
    drawdowns_path = output_dir / "drawdowns.csv"

    index_rows = load_index_rows(DEFAULT_START_DATE, DEFAULT_END_DATE)
    composite_rows = load_composite_rows(None, DEFAULT_END_DATE)
    spliced_rows = build_spliced_series(composite_rows, index_rows, DEFAULT_START_DATE)

    rate_rows = load_rate_rows(None, DEFAULT_END_DATE)
    rate_dates = [row_date for row_date, _ in rate_rows]
    rate_map = dict(rate_rows)

    proxy_rows = load_proxy_rows(spliced_rows[0][0], DEFAULT_END_DATE)
    proxy_dates = [row_date for row_date, _ in proxy_rows]
    proxy_map = dict(proxy_rows)

    variants = [
        ("NDX only | financing excluded", build_leveraged_series(index_rows, rate_dates, rate_map, leverage=3.0, include_financing_cost=False)),
        ("NDX only | financing included", build_leveraged_series(index_rows, rate_dates, rate_map, leverage=3.0, include_financing_cost=True)),
        ("Composite splice | financing excluded", build_leveraged_series(spliced_rows, rate_dates, rate_map, leverage=3.0, include_financing_cost=False)),
        ("Composite splice | financing included", build_leveraged_series(spliced_rows, rate_dates, rate_map, leverage=3.0, include_financing_cost=True)),
    ]

    summary_rows: list[dict[str, object]] = []
    annual_rows: list[dict[str, object]] = []
    drawdown_rows: list[dict[str, object]] = []

    for strategy_name, series in variants:
        result = simulate_staged_strategy(
            series=series,
            rate_dates=rate_dates,
            rate_map=rate_map,
            proxy_dates=proxy_dates,
            proxy_map=proxy_map,
            strategy_name=strategy_name,
        )
        summary_rows.append(summarize_variant(strategy_name, result))
        for row in result["annual_rows"]:
            annual_rows.append(
                {
                    "strategy": strategy_name,
                    "year": row["year"],
                    "start_date": row["start_date"].isoformat(),
                    "end_date": row["end_date"].isoformat(),
                    "period_type": "partial" if row["is_partial"] else "full",
                    "return": round(row["return"], 6),
                }
            )
        for episode in result["drawdowns"]:
            drawdown_rows.append(
                {
                    "strategy": strategy_name,
                    "rank": episode.rank,
                    "peak_date": episode.peak_date.isoformat(),
                    "trough_date": episode.trough_date.isoformat(),
                    "recovery_date": episode.recovery_date.isoformat() if episode.recovery_date else "",
                    "drawdown": round(episode.drawdown, 6),
                    "peak_to_trough_days": episode.peak_to_trough_days,
                    "peak_to_recovery_days": episode.peak_to_recovery_days if episode.peak_to_recovery_days is not None else "",
                    "recovered": int(episode.recovered),
                }
            )

    write_rows_csv(summary_path, summary_rows)
    write_rows_csv(annual_path, annual_rows)
    write_rows_csv(drawdowns_path, drawdown_rows)

    print(f"wrote {summary_path}")
    print(f"wrote {annual_path}")
    print(f"wrote {drawdowns_path}")
    for row in summary_rows:
        print(
            f"{row['strategy']}: "
            f"final={row['final_multiple']:.4f}, "
            f"CAGR={row['cagr']:.4%}, "
            f"MDD={row['mdd']:.4%}, "
            f"trades={row['trades']}, "
            f"small_hits={row['small_exit_hits']}, "
            f"large_hits={row['large_exit_hits']}"
        )


if __name__ == "__main__":
    main()
