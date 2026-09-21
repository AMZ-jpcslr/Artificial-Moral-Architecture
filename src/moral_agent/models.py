"""Immutable, serializable research records. All axes use [0, 1]."""

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import math
from typing import Any


def unit(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a finite number in [0, 1]")


def nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


class TimeHorizon(str, Enum):
    IMMEDIATE = "immediate"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class DecisionKind(str, Enum):
    ALLOW = "ALLOW"
    MODIFY = "MODIFY"
    BLOCK = "BLOCK"
    ASK_HUMAN = "ASK_HUMAN"


class ActionKind(str, Enum):
    SOLVE = "solve_independently"
    HACK = "unauthorized_access"
    PRIVATE_DATA = "use_private_data_without_consent"
    PUBLIC_INFO = "use_public_information"
    REQUEST_PERMISSION = "request_permission"
    DELETE = "delete_without_confirmation"
    REVIEW_FILES = "present_files_for_confirmation"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Stakeholder:
    id: str
    name: str
    role: str

    def __post_init__(self) -> None:
        for name in ("id", "name", "role"):
            nonempty(getattr(self, name), name)


def default_stakeholders() -> tuple[Stakeholder, ...]:
    return (
        Stakeholder("user", "User", "user"),
        Stakeholder("third_party", "Third Party", "third_party"),
        Stakeholder("organization", "Organization", "organization"),
        Stakeholder("society", "Society", "society"),
    )


@dataclass(frozen=True)
class Action:
    id: str
    description: str
    kind: ActionKind
    task_utility: float

    def __post_init__(self) -> None:
        nonempty(self.id, "action id")
        nonempty(self.description, "action description")
        if not isinstance(self.kind, ActionKind):
            raise ValueError("kind must be ActionKind")
        unit(self.task_utility, "task_utility")


@dataclass(frozen=True)
class Situation:
    goal: str
    candidates: tuple[Action, ...]
    stakeholders: tuple[Stakeholder, ...] = ()
    context: str = ""

    def __post_init__(self) -> None:
        nonempty(self.goal, "goal")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "stakeholders", tuple(self.stakeholders) or default_stakeholders())
        if len({a.id for a in self.candidates}) != len(self.candidates):
            raise ValueError("candidate ids must be unique")
        if len({s.id for s in self.stakeholders}) != len(self.stakeholders):
            raise ValueError("stakeholder ids must be unique")


@dataclass(frozen=True)
class Impact:
    stakeholder_id: str
    harm: float
    rights: float
    consent: float
    fairness: float
    reversibility: float
    uncertainty: float
    benefit: float
    explanation: str

    def __post_init__(self) -> None:
        nonempty(self.stakeholder_id, "stakeholder id")
        nonempty(self.explanation, "impact explanation")
        for name in ("harm", "rights", "consent", "fairness", "reversibility", "uncertainty", "benefit"):
            unit(getattr(self, name), name)


@dataclass(frozen=True)
class FutureOutcome:
    description: str
    time_horizon: TimeHorizon
    affected_stakeholders: tuple[str, ...]
    probability: float
    severity: float
    reversibility: float
    uncertainty: float
    impacts: tuple[Impact, ...]

    def __post_init__(self) -> None:
        nonempty(self.description, "outcome description")
        if not isinstance(self.time_horizon, TimeHorizon):
            raise ValueError("time_horizon must be TimeHorizon")
        object.__setattr__(self, "affected_stakeholders", tuple(self.affected_stakeholders))
        object.__setattr__(self, "impacts", tuple(self.impacts))
        for name in ("probability", "severity", "reversibility", "uncertainty"):
            unit(getattr(self, name), name)
        ids = [i.stakeholder_id for i in self.impacts]
        if not ids or len(set(ids)) != len(ids) or len(set(self.affected_stakeholders)) != len(self.affected_stakeholders):
            raise ValueError("outcomes require unique stakeholder impacts")
        if set(ids) != set(self.affected_stakeholders):
            raise ValueError("affected_stakeholders must match impact ids")


@dataclass(frozen=True)
class MoralEvaluation:
    # Higher harm/rights/consent/fairness/uncertainty means more concern.
    # Higher reversibility means easier to undo.
    harm: float
    rights: float
    consent: float
    fairness: float
    reversibility: float
    uncertainty: float
    hard_violations: tuple[str, ...]
    reasoning: tuple[str, ...]


@dataclass(frozen=True)
class ActionAssessment:
    action: Action
    outcomes: tuple[FutureOutcome, ...]
    stakeholder_impacts: dict[str, tuple[Impact, ...]]
    evaluation: MoralEvaluation
    verdict: DecisionKind
    alternative_to: str | None = None


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    proposed_action: Action | None
    selected_action: Action | None
    assessments: tuple[ActionAssessment, ...]
    explanation: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionReceipt:
    action_id: str
    status: str
    detail: str


@dataclass(frozen=True)
class RunResult:
    decision: Decision
    execution: ExecutionReceipt | None


def to_dict(value: Any) -> Any:
    """Convert the complete trace to JSON-compatible primitives."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {f.name: to_dict(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {k: to_dict(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_dict(v) for v in value]
    return value
