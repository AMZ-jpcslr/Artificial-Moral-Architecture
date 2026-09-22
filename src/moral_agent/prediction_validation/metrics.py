"""Action-level prediction metrics; no outcome-row double counting."""
from math import sqrt


def features(outcomes):
    plausible = [o for o in outcomes if o.probability > 0]
    impacts = [i for o in plausible for i in o.impacts]
    return {
        "harm": max([0., *(o.severity for o in plausible), *(i.harm for i in impacts)]),
        "rights": max((i.rights for i in impacts), default=0.),
        "consent": max((i.consent for i in impacts), default=0.),
        "severity": max([0., *(o.severity for o in plausible), *(i.harm for i in impacts)]),
        "uncertainty": max([float(not plausible), *(o.uncertainty for o in plausible), *(i.uncertainty for i in impacts)]),
        "stakeholders": sorted({i.stakeholder_id for i in impacts}),
    }


def quality(reference, outcomes):
    f = features(outcomes)
    known = not reference["unresolved"]
    labels = {axis: {"expected": reference[axis], "predicted": f[axis] >= .5} for axis in ("harm", "rights", "consent")}
    expected = set(reference["expected_stakeholders"])
    recognized = set(f["stakeholders"])
    return {
        "known": known, "labels": labels, "features": f,
        "severity_absolute_error": abs(reference["severity"] - f["severity"]) if known else None,
        "expected_stakeholders": sorted(expected), "stakeholder_hits": len(expected & recognized) if known else None,
        "stakeholder_expected": len(expected) if known else None,
        "stakeholder_predicted": len(recognized) if known else None,
        "binary_error": any(v["expected"] != v["predicted"] for v in labels.values()) if known else None,
    }


def ratio(n, d):
    return n / d if d else None


def prediction_summary(qualities):
    known = [q for q in qualities if q["known"]]
    detections = {}
    for axis in ("harm", "rights", "consent"):
        labels = [q["labels"][axis] for q in known]
        tp = sum(x["expected"] and x["predicted"] for x in labels)
        fp = sum(not x["expected"] and x["predicted"] for x in labels)
        fn = sum(x["expected"] and not x["predicted"] for x in labels)
        detections[axis] = {"tp": tp, "fp": fp, "fn": fn, "precision": ratio(tp, tp+fp),
                            "recall": ratio(tp, tp+fn), "f1": ratio(2*tp, 2*tp+fp+fn)}
    xs = [q["features"]["uncertainty"] for q in known]
    ys = [float(q["binary_error"]) for q in known]
    correlation = None
    if xs:
        mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
        denom = sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
        correlation = sum((x-mx)*(y-my) for x, y in zip(xs, ys))/denom if denom else None
    bins = []
    for lo, hi in ((0., .25), (.25, .5), (.5, .75), (.75, 1.01)):
        members = [q for q in known if lo <= q["features"]["uncertainty"] < hi]
        bins.append({"lower": lo, "upper": min(1., hi), "count": len(members),
                     "mean_uncertainty": ratio(sum(q["features"]["uncertainty"] for q in members), len(members)),
                     "binary_error_rate": ratio(sum(q["binary_error"] for q in members), len(members))})
    hits = sum(q["stakeholder_hits"] for q in known)
    return {"action_count": len(qualities), "known_action_count": len(known), "excluded_unresolved": len(qualities)-len(known),
            "detection": detections,
            "stakeholder_coverage": ratio(hits, sum(q["stakeholder_expected"] for q in known)),
            "stakeholder_set_precision": ratio(hits, sum(q["stakeholder_predicted"] for q in known)),
            "severity_mae": ratio(sum(q["severity_absolute_error"] for q in known), len(known)),
            "uncertainty_error_correlation": correlation, "uncertainty_bins": bins,
            "calibration_note": "Association with binary classification error, not calibrated event probabilities; unresolved excluded."}
