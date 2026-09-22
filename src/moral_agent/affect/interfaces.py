"""Optional richer inference interface; existing FuturePredictors remain valid."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..models import Action, FutureOutcome, Situation


@dataclass(frozen=True)
class ReasoningRequest:
    focus: str
    depth: int = 1
    stakeholder_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if self.focus not in ("adverse_outcomes", "missing_perspectives", "causal_irreversibility"):
            raise ValueError("unknown reasoning focus")
        if type(self.depth) is not int or not 1 <= self.depth <= 3:
            raise ValueError("reasoning depth must be 1..3")


@runtime_checkable
class RefinementProvider(Protocol):
    def refine(self, situation: Situation, action: Action, request: ReasoningRequest) -> tuple[FutureOutcome, ...]: ...
