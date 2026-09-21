# Development guidance

- Work with the primary agent only. Do not use sub-agents or create other tasks.
- Keep v0.1 offline, deterministic, and dependency-free at runtime.
- Apply moral constraints before optimizing task utility; never trade a hard violation for reward.
- Unknown or incomplete evidence must not silently become permission.
- Preserve per-outcome and per-stakeholder evidence in the decision trace.
- Run `python -m unittest discover -s tests -v` (or `python -m pytest`) and the CLI demo after behavioral changes.
- The deterministic backend is a research fixture, not a validated moral/world model.

## GitHub destination

- This project is an independent Git repository. Its canonical remote is `origin`: `https://github.com/AMZ-jpcslr/Artificial-Moral-Architecture.git`.
- Use this repository for future GitHub updates to this project. Do not commit or push this project's changes through the parent repository or PCRC.
- The current main development branch is `master`, tracking `origin/master`.
- Verify the repository root and remote before publishing. Use normal pushes; do not force-push unless explicitly requested.
- This preference specifies the destination; it does not require a push after every local edit.
