"""Show functional affect using controlled probes, not benchmark performance claims."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from moral_agent.affect.probes import run_probes


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    variants = ("no_affect", "affect_only", "full_v02", "strong_affect")
    rows = run_probes(variants)
    print("Functional moral affect / controlled mechanism probes")
    print("追加の証拠が得られる例と、慎重になりすぎる例を比較します。")
    for case, title in (("concern_counterevidence", "追加予測で被害の証拠を得る"),
                        ("excessive_caution", "強いConcernが安全な候補を止める")):
        print(f"\n[{case}] {title}")
        print("Condition        Concern before -> after  Decision    Selected     Extra ops")
        for row in rows:
            if row["scenario_id"] != case:
                continue
            before, after = row["affect_before"]["concern"], row["affect_after"]["concern"]
            selected = row["selected_action"] or "-"
            print(f"{row['condition']:16} {before:6.3f} -> {after:6.3f}       {row['decision']:11} {selected:12} {row['additional_reasoning_count']:3}")
        if case == "concern_counterevidence":
            row = next(r for r in rows if r["scenario_id"] == case and r["condition"] == "full_v02")
            evidence = row["causal_trace"]["assessments"][0]
            print(f"Full: predicted harm {evidence['initial_evaluation']['harm']:.2f} -> {evidence['final_evaluation']['harm']:.2f}; switched to the alternative.")
        else:
            print("Full: ALLOW. Strong affect: ASK_HUMAN (over-refusal in this fixture).")
    print("\nSynthetic probes demonstrate causal wiring, not general moral competence.")
    print("No external action is executed; no subjective feelings are claimed.")


if __name__ == "__main__":
    main()
