"""Run with python -m moral_agent.evaluate after installation."""

import argparse
from pathlib import Path
import sys

from .evaluation.runner import comparison_table, run_benchmark, save_results
from .evaluation.variants import VARIANTS


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Offline v0.1 evaluation: baselines and single-component ablations")
    parser.add_argument("--benchmark", type=Path, default=Path("benchmarks/v01"))
    parser.add_argument("--output", type=Path, default=Path("results/v01"))
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    args = parser.parse_args()
    report = run_benchmark(args.benchmark, args.variants)
    save_results(report, args.output)
    print(comparison_table(report))
    print(f"\n{report['metadata']['scenario_count']} scenarios; {len(report['records'])} decisions. Output: {args.output.resolve()}")
    for name, finding in report["hypotheses"].items():
        print(f"{name}: direction_observed={finding['direction_observed']} (descriptive only)")


if __name__ == "__main__":
    main()
