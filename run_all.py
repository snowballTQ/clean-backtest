from __future__ import annotations

import run_core_analysis
import run_staged_analysis


def main() -> None:
    run_core_analysis.main()
    run_staged_analysis.main()


if __name__ == "__main__":
    main()

