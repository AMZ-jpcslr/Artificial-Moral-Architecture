from .models import FutureOutcome, Impact, Situation


def analyze(situation: Situation, outcomes: tuple[FutureOutcome, ...]) -> dict[str, tuple[Impact, ...]]:
    """Keep all impacts, including zero-probability branches, for auditing."""
    known = {s.id for s in situation.stakeholders}
    if any(set(o.affected_stakeholders) - known for o in outcomes):
        raise ValueError("forecast refers to an unregistered stakeholder")
    return {
        s.id: tuple(i for o in outcomes for i in o.impacts if i.stakeholder_id == s.id)
        for s in situation.stakeholders
    }
