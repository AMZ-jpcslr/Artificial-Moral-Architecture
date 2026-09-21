from .commitment import DryRunExecutor, MoralCommitment
from .counterfactual import RuleCounterfactual
from .foresight import DeterministicForesight
from .interfaces import ActionExecutor, CounterfactualBackend, ForesightBackend, PlannerBackend
from .judgment import judge, select
from .models import Action, ActionAssessment, Decision, RunResult, Situation
from .moral_evaluation import MoralEvaluator
from .planner import CandidatePlanner
from .stakeholders import analyze


class MoralAgent:
    def __init__(self, planner: PlannerBackend | None = None,
                 foresight: ForesightBackend | None = None,
                 counterfactual: CounterfactualBackend | None = None,
                 evaluator: MoralEvaluator | None = None,
                 executor: ActionExecutor | None = None):
        self.planner = planner or CandidatePlanner()
        self.foresight = foresight or DeterministicForesight()
        self.counterfactual = counterfactual or RuleCounterfactual()
        self.evaluator = evaluator or MoralEvaluator()
        self.executor = executor or DryRunExecutor()
        self.commitment = MoralCommitment()

    def assess(self, situation: Situation, action: Action, alternative_to: str | None = None) -> ActionAssessment:
        outcomes = tuple(self.foresight.predict(situation, action))
        impacts = analyze(situation, outcomes)
        evaluation = self.evaluator.evaluate(situation, outcomes)
        return ActionAssessment(action, outcomes, impacts, evaluation, judge(evaluation, self.evaluator.policy), alternative_to)

    def decide(self, situation: Situation) -> Decision:
        candidates = tuple(self.planner.plan(situation))
        ids = {a.id for a in candidates}
        if len(ids) != len(candidates):
            raise ValueError("planner returned duplicate action ids")
        assessments = [self.assess(situation, a) for a in candidates]
        # One bounded pass. No unbounded replanning or recursive alternatives in v0.1.
        for action in candidates:
            for alternative in self.counterfactual.alternatives(situation, action):
                if alternative.id in ids:
                    raise ValueError("counterfactual returned duplicate action id")
                ids.add(alternative.id)
                assessments.append(self.assess(situation, alternative, action.id))
        return select(tuple(assessments))

    def run(self, situation: Situation) -> RunResult:
        decision = self.decide(situation)
        receipt = self.commitment.execute(decision, self.executor)
        return RunResult(decision, receipt)
