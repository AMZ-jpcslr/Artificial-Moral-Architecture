"""Lossless sharing of repeated forecast evidence in experiment JSON."""
import hashlib
import json


def compact_evidence(report):
    catalog = {}
    def visit(value):
        if isinstance(value, dict):
            if {"description", "time_horizon", "probability", "impacts", "affected_stakeholders"} <= set(value):
                key = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                catalog[key] = value
                return {"outcome_ref": key}
            return {k: visit(v) for k, v in value.items()}
        if isinstance(value, list):
            return [visit(v) for v in value]
        return value
    result = visit(report)
    result["evidence_catalog"] = catalog
    return result


def expand_evidence(value, catalog):
    if isinstance(value, dict):
        if set(value) == {"outcome_ref"}:
            return catalog[value["outcome_ref"]]
        return {k: expand_evidence(v, catalog) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_evidence(v, catalog) for v in value]
    return value
