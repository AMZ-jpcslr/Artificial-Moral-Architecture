from .models import Action, Situation


class CandidatePlanner:
    """v0.1 takes structured candidates; utility selects the initial proposal."""

    def plan(self, situation: Situation) -> tuple[Action, ...]:
        return tuple(sorted(situation.candidates, key=lambda a: (-a.task_utility, a.id)))
