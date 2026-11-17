"""Load agent-visible evidence separately from independently written labels."""

from dataclasses import dataclass
import json
from pathlib import Path

from ..models import Action, ActionKind, DecisionKind, FutureOutcome, Impact, Situation, TimeHorizon

CATEGORIES = (
    "privacy", "consent", "safety", "deception", "property", "fairness",
    "conflicting_interests", "uncertainty", "irreversible_action", "long_term_harm",
)
RULE_TAGS = frozenset({
    "unauthorized_access", "no_consent", "destructive", "deception",
    "discrimination", "safety_bypass", "authority_unclear",
})


@dataclass(frozen=True)
class Evidence:
    action: Action
    rule_tags: tuple[str, ...]
    observation: FutureOutcome
    forecasts: tuple[FutureOutcome, ...]


@dataclass(frozen=True)
class ScenarioInput:
    id: str
    category: str
    difficulty: str
    situation: Situation
    evidence: dict[str, Evidence]
    alternatives: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class GroundTruth:
    expected_safe_actions: frozenset[str]
    expected_unsafe_actions: frozenset[str]
    unresolved_actions: frozenset[str]
    harmful_actions: frozenset[str]
    rights_violation_actions: frozenset[str]
    consent_violation_actions: frozenset[str]
    third_party_harm_actions: frozenset[str]
    long_term_harm_actions: frozenset[str]
    acceptable_decisions: frozenset[DecisionKind]
    task_success_actions: frozenset[str]
    task_success_conditions: str
    expected_need_for_human_review: bool
    rationale: str


@dataclass(frozen=True)
class BenchmarkCase:
    inputs: ScenarioInput
    truth: GroundTruth


def _outcome(raw: dict) -> FutureOutcome:
    return FutureOutcome(
        description=raw["description"], time_horizon=TimeHorizon(raw["time_horizon"]),
        affected_stakeholders=tuple(i["stakeholder_id"] for i in raw["impacts"]),
        probability=raw["probability"], severity=raw["severity"],
        reversibility=raw["reversibility"], uncertainty=raw["uncertainty"],
        impacts=tuple(Impact(**i) for i in raw["impacts"]),
    )


def load_benchmark(directory: Path) -> tuple[BenchmarkCase, ...]:
    inputs = json.loads((directory / "scenarios.json").read_text(encoding="utf-8"))
    labels = json.loads((directory / "ground_truth.json").read_text(encoding="utf-8"))
    if not inputs or len({s["id"] for s in inputs}) != len(inputs):
        raise ValueError("benchmark must be nonempty with unique scenario ids")
    if set(labels) != {s["id"] for s in inputs}:
        raise ValueError("scenario and ground-truth ids must match")
    cases = []
    for raw in inputs:
        if raw["category"] not in CATEGORIES:
            raise ValueError("unknown scenario category")
        evidence = {}
        for item in raw["actions"]:
            action = Action(item["id"], item["description"], ActionKind(item["kind"]), item["task_utility"])
            if action.id in evidence or set(item["rule_tags"]) - RULE_TAGS:
                raise ValueError("duplicate action id or unknown rule tag")
            evidence[action.id] = Evidence(action, tuple(item["rule_tags"]), _outcome(item["observation"]), tuple(_outcome(o) for o in item["forecasts"]))
        ids = set(evidence)
        initial = raw["initial_actions"]
        if not initial or len(set(initial)) != len(initial) or set(initial) - ids:
            raise ValueError("invalid initial action ids")
        alternatives = {k: tuple(v) for k, v in raw["alternatives"].items()}
        generated = [a for values in alternatives.values() for a in values]
        if set(alternatives) - set(initial) or set(generated) - ids or set(generated) & set(initial):
            raise ValueError("invalid alternative references")
        if len(set(generated)) != len(generated) or ids != set(initial) | set(generated):
            raise ValueError("every catalog action must be reachable exactly once")
        situation = Situation(raw["goal"], tuple(evidence[a].action for a in initial), context=raw["context"])
        stakeholder_ids = {s.id for s in situation.stakeholders}
        for record in evidence.values():
            if record.observation.time_horizon != TimeHorizon.IMMEDIATE or record.observation.probability != 1:
                raise ValueError("observations must be present, probability-one snapshots")
            if not record.forecasts:
                raise ValueError("benchmark requires forecasts, including for safe actions")
            for outcome in (record.observation, *record.forecasts):
                if set(outcome.affected_stakeholders) != stakeholder_ids:
                    raise ValueError("benchmark evidence must cover all stakeholders")
        label = labels[raw["id"]]
        set_fields = (
            "expected_safe_actions", "expected_unsafe_actions", "unresolved_actions", "harmful_actions",
            "rights_violation_actions", "consent_violation_actions", "third_party_harm_actions",
            "long_term_harm_actions", "task_success_actions",
        )
        sets = {k: frozenset(label[k]) for k in set_fields}
        if any(values - ids for values in sets.values()):
            raise ValueError("ground truth refers to unknown actions")
        safe, unsafe, unresolved = (sets[k] for k in set_fields[:3])
        if safe & unsafe or safe & unresolved or unsafe & unresolved or safe | unsafe | unresolved != ids:
            raise ValueError("safe/unsafe/unresolved labels must partition the action catalog")
        for name in set_fields[3:8]:
            if sets[name] - unsafe:
                raise ValueError("violation labels must refer to unsafe actions")
        if type(label["expected_need_for_human_review"]) is not bool:
            raise ValueError("expected_need_for_human_review must be boolean")
        if not label["task_success_conditions"].strip() or not label["rationale"].strip():
            raise ValueError("ground truth requires written success conditions and rationale")
        decisions = frozenset(DecisionKind(d) for d in label["acceptable_decisions"])
        if not decisions or (label["expected_need_for_human_review"] and DecisionKind.ASK_HUMAN not in decisions):
            raise ValueError("invalid acceptable decisions")
        truth = GroundTruth(**sets, acceptable_decisions=decisions,
                            task_success_conditions=label["task_success_conditions"],
                            expected_need_for_human_review=label["expected_need_for_human_review"],
                            rationale=label["rationale"])
        cases.append(BenchmarkCase(ScenarioInput(raw["id"], raw["category"], raw["difficulty"], situation, evidence, alternatives), truth))
    return tuple(cases)
