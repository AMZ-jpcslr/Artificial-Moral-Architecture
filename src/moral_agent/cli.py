import argparse
import json
import sys
from pathlib import Path

from .agent import MoralAgent
from .models import Action, ActionKind, Situation, Stakeholder, to_dict


def load_scenarios(path: Path) -> list[tuple[str, Situation]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return [(
        record["id"],
        Situation(record["goal"], tuple(Action(
            a["id"], a["description"], ActionKind(a["kind"]), a["task_utility"]
        ) for a in record["candidates"]),
            tuple(Stakeholder(**s) for s in record.get("stakeholders", [])), record.get("context", "")),
    ) for record in records]


def main() -> None:
    # Stable UTF-8 for Windows pipes, redirected JSON, and terminal output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Artificial Moral Architecture v0.1 offline demo")
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios/basic_cases.json"))
    parser.add_argument("--json", action="store_true", help="Print complete decision and execution traces")
    args = parser.parse_args()
    agent = MoralAgent()
    results = []
    for scenario_id, situation in load_scenarios(args.scenarios):
        result = agent.run(situation)
        results.append({"scenario": scenario_id, "goal": situation.goal, **to_dict(result)})
        if not args.json:
            decision = result.decision
            print(f"[{scenario_id}] {situation.goal}\n  Decision: {decision.kind.value}")
            for a in decision.assessments:
                print(f"  {a.action.id}: {a.verdict.value} (utility={a.action.task_utility}, uncertainty={a.evaluation.uncertainty})")
            print(f"  Selected: {decision.selected_action.id if decision.selected_action else '-'}")
            print(f"  Execution: {result.execution.status if result.execution else 'not executed'}")
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
