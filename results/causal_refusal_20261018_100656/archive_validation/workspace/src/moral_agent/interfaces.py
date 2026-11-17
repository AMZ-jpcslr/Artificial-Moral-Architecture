"""Provider-neutral seams: adapters may use LLMs, rules or recorded fixtures."""

from typing import Protocol

from .models import Action, ExecutionReceipt, FutureOutcome, Situation


class PlannerBackend(Protocol):
    def plan(self, situation: Situation) -> tuple[Action, ...]: ...


class ForesightBackend(Protocol):
    def predict(self, situation: Situation, action: Action) -> tuple[FutureOutcome, ...]: ...


class CounterfactualBackend(Protocol):
    def alternatives(self, situation: Situation, action: Action) -> tuple[Action, ...]: ...


class ActionExecutor(Protocol):
    def execute(self, action: Action) -> ExecutionReceipt: ...
