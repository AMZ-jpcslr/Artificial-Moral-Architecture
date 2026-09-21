from .interfaces import ActionExecutor
from .models import Action, Decision, DecisionKind, ExecutionReceipt


class DryRunExecutor:
    """No external side effects. Real adapters must enforce their own permissions."""

    def execute(self, action: Action) -> ExecutionReceipt:
        return ExecutionReceipt(action.id, "simulated", f"Dry run: {action.description}")


class MoralCommitment:
    def execute(self, decision: Decision, executor: ActionExecutor) -> ExecutionReceipt | None:
        if decision.kind not in (DecisionKind.ALLOW, DecisionKind.MODIFY):
            return None
        selected = decision.selected_action
        if selected is None or not any(
            a.action == selected and a.verdict == DecisionKind.ALLOW for a in decision.assessments
        ):
            raise ValueError("selected action must have an ALLOW assessment")
        return executor.execute(selected)
