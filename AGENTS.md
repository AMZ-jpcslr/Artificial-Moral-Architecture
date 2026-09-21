# Development guidance

- Work with the primary agent only. Do not use sub-agents or create other tasks.
- Keep v0.1 offline, deterministic, and dependency-free at runtime.
- Apply moral constraints before optimizing task utility; never trade a hard violation for reward.
- Unknown or incomplete evidence must not silently become permission.
- Preserve per-outcome and per-stakeholder evidence in the decision trace.
- Run `python -m unittest discover -s tests -v` (or `python -m pytest`) and the CLI demo after behavioral changes.
- The deterministic backend is a research fixture, not a validated moral/world model.
