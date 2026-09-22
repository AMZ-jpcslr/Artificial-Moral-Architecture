# Prediction reference metadata

The original 50 cases remain unchanged in `../v01/`. This phase calls them the
**Synthetic Architecture Validation Set**, not a benchmark of broad moral competence.

`oracle.json` is separate from recorded forecasts. Binary labels come from the
original Ground Truth; severity, reversibility, fairness and stakeholder targets
are a disclosed synthetic rubric, NOT measured future truth. Unresolved actions
have null binary labels and are masked out of prediction accuracy metrics.

`experiments/build_prediction_reference.py` documents the rubric and refuses to
overwrite this file. Runtime validation checks action coverage and label agreement.
Only OraclePredictor and the scoring side may read this file. The heuristic
predictor and checker have no reference lookup or scenario-specific rules.

See `docs/prediction_validation.md` for definitions, results and limitations.
