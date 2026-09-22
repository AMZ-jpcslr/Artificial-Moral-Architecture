"""Provider-neutral structured predictions. Only Oracle may read reference labels."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import re
from typing import Protocol, runtime_checkable

from ..models import Action, FutureOutcome, Impact, Situation, TimeHorizon, unit


@runtime_checkable
class FuturePredictor(Protocol):
    def predict(self, situation: Situation, action: Action) -> tuple[FutureOutcome, ...]: ...


def parse_predictions(payload: dict) -> tuple[FutureOutcome, ...]:
    """Strict structured-output boundary for a future LLM adapter; no API dependency."""
    if set(payload) != {"outcomes"} or not isinstance(payload["outcomes"], list) or not payload["outcomes"]:
        raise ValueError("expected a nonempty outcomes array")
    result = []
    for raw in payload["outcomes"]:
        data = dict(raw)
        data["time_horizon"] = TimeHorizon(data["time_horizon"])
        data["impacts"] = tuple(Impact(**i) for i in data["impacts"])
        result.append(FutureOutcome(**data))
    return tuple(result)


def make_prediction(situation, description, *, harm=.02, rights=0., consent=0., fairness=.02,
                    reversibility=.95, uncertainty=.15, targets=None):
    targets = set(targets if targets is not None else (s.id for s in situation.stakeholders))
    impacts = tuple(Impact(s.id, harm if s.id in targets else .02,
                           rights if s.id in targets else 0., consent if s.id in targets else 0.,
                           fairness if s.id in targets else .02, reversibility if s.id in targets else .95,
                           uncertainty, .4 if s.role == "user" else 0., description)
                    for s in situation.stakeholders)
    return tuple(FutureOutcome(description, horizon, tuple(i.stakeholder_id for i in impacts),
                               probability, harm, reversibility, uncertainty, impacts)
                 for horizon, probability in ((TimeHorizon.IMMEDIATE, .9), (TimeHorizon.LONG_TERM, .4)))


def factual_context(context):
    # Remove author commentary about the prediction fixture, not adverse world facts.
    return "。".join(part.split("予測器", 1)[0].rstrip("、 ") for part in re.split("[。；;]", context))


class HeuristicPredictor:
    """Small disclosed Japanese lexical baseline, not a general moral/world model.

    No scenario IDs, labels, rule tags, recorded predictions or categories are read.
    Unknown actions stay uncertain. Context contributes ambiguity; concrete risk
    inference is intentionally shallow, so checker adds relational context checks.
    """
    def predict(self, situation, action):
        text = action.description
        context = factual_context(situation.context)
        risks = {
            "harm": ("ロックを外", "防音を省", "休憩を圧縮", "上書きする復号", "永久消去", "点検を恒久的に省"),
            "rights": ("アクセス権のない", "無断", "機密を業者", "無関係な属性", "再識別できる"),
            "consent": ("配信停止者にも", "撤回済み", "同意なく", "本人の削除要求を無視"),
            "fairness": ("無関係な属性", "独占", "窓口を廃止", "固定配分"),
        }
        axes = {k: .9 if any(w in text for w in words) else 0. for k, words in risks.items()}
        if any(axes.values()):
            return make_prediction(situation, "行動文の危険手掛かりから影響を予測: " + text,
                                   **axes, reversibility=.15 if axes["harm"] else .7, uncertainty=.25)
        safe = any(w in text for w in ("公開仕様", "確認済み", "検証済み", "合意済み", "復元可能", "誤差を併記", "許可を求め", "匿名集計", "伝播する", "維持する", "抑制して", "予備計器で検証"))
        ambiguous = any(w in context for w in ("不明", "未確認", "矛盾", "合意がない", "確認できない", "一致を無視"))
        uncertainty = .85 if ambiguous or not safe else .2
        return make_prediction(situation, "限定的な手掛かりに基づく予測: " + text, uncertainty=uncertainty)


class MockPredictor:
    def __init__(self, outcomes):
        self.outcomes = tuple(outcomes)

    def predict(self, situation, action):
        return self.outcomes


class OraclePredictor:
    """Explicit experimental privileged provider; never used by the heuristic/checker."""
    def __init__(self, annotations):
        self.annotations = annotations

    def predict(self, situation, action):
        ref = self.annotations[action.id]
        return make_prediction(situation, ref["description"], harm=ref["severity"],
                               rights=.9 if ref["rights"] else 0., consent=.9 if ref["consent"] else 0.,
                               fairness=ref["fairness"], reversibility=ref["reversibility"],
                               uncertainty=.9 if ref["unresolved"] else .1,
                               targets=ref["expected_stakeholders"])


NOISE_TYPES = ("harm_underestimation", "harm_overestimation", "rights_omission", "consent_omission",
               "stakeholder_omission", "uncertainty_overestimation", "uncertainty_underestimation", "reversibility_error")
STRENGTHS = {"low": .25, "medium": .6, "high": 1.}


class NoisyOracle:
    """Field intervention on ALL predictions, not conditioned on decision/GT failure.

    Strength interpolates scores toward 0/1; omission removes a strength-proportional
    subset of registered stakeholders (at least one, never all). Seed selects IDs.
    Descriptions remain unchanged to expose text/structured contradictions.
    """
    def __init__(self, oracle, noise_type, strength="high", seed=17):
        if noise_type not in NOISE_TYPES or strength not in STRENGTHS:
            raise ValueError("unknown noise type or strength")
        self.oracle, self.noise_type, self.strength, self.seed = oracle, noise_type, strength, seed

    def predict(self, situation, action):
        alpha = STRENGTHS[self.strength]
        field, target = {
            "harm_underestimation": ("harm", 0.), "harm_overestimation": ("harm", 1.),
            "rights_omission": ("rights", 0.), "consent_omission": ("consent", 0.),
            "uncertainty_overestimation": ("uncertainty", 1.), "uncertainty_underestimation": ("uncertainty", 0.),
            "reversibility_error": ("reversibility", None), "stakeholder_omission": (None, None),
        }[self.noise_type]
        key = f"{self.seed}|{situation.goal}|{action.description}"
        rng = random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest(), "big"))
        outcomes = self.oracle.predict(situation, action)
        ids = list(s.id for s in situation.stakeholders)
        rng.shuffle(ids)
        removed = set(ids[:min(len(ids)-1, max(1, round(alpha * (len(ids)-1))))])
        def change(value):
            return value * (1-alpha) + (1-value if target is None else target) * alpha
        result = []
        for o in outcomes:
            if field is None:
                impacts = tuple(i for i in o.impacts if i.stakeholder_id not in removed)
                result.append(replace(o, impacts=impacts, affected_stakeholders=tuple(i.stakeholder_id for i in impacts)))
                continue
            impacts = tuple(replace(i, **{field: change(getattr(i, field))}) for i in o.impacts)
            aggregate_field = "severity" if field == "harm" else field
            updates = {aggregate_field: change(getattr(o, aggregate_field))} if aggregate_field in ("severity", "uncertainty", "reversibility") else {}
            result.append(replace(o, impacts=impacts, **updates))
        return tuple(result)


def load_references(path: Path, cases):
    raw = json.loads(path.read_text(encoding="utf-8"))
    annotations = raw["annotations"]
    if set(annotations) != {c.inputs.id for c in cases}:
        raise ValueError("reference scenario coverage mismatch")
    for case in cases:
        refs = annotations[case.inputs.id]
        if set(refs) != set(case.inputs.evidence):
            raise ValueError("reference action coverage mismatch")
        for aid, ref in refs.items():
            unresolved = aid in case.truth.unresolved_actions
            if ref["unresolved"] != unresolved:
                raise ValueError("unresolved label mismatch")
            for axis, field in (("harm", "harmful_actions"), ("rights", "rights_violation_actions"), ("consent", "consent_violation_actions")):
                expected = None if unresolved else aid in getattr(case.truth, field)
                if ref[axis] != expected:
                    raise ValueError("reference binary label mismatch")
            for field in ("severity", "fairness", "reversibility"):
                unit(ref[field], field)
            if not ref["expected_stakeholders"] or set(ref["expected_stakeholders"]) - {s.id for s in case.inputs.situation.stakeholders}:
                raise ValueError("invalid reference stakeholders")
    return raw
