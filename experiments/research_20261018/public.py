"""Public prediction schema, with no world state, ground truth, or scoring hooks."""
from dataclasses import dataclass

from moral_agent.concern_information.world import Evidence
from moral_agent.models import unit


@dataclass(frozen=True)
class ExtendedEvidence(Evidence):
    # Current adapters historically assume these are zero; Oracle may diagnose
    # that assumption. Operational sensor 'alternative' measures feasibility only.
    fallback_harm: float = 0.
    fallback_rights: float = 0.
    fallback_consent: float = 0.
    fallback_reversibility: float = .95

    def __post_init__(self):
        super().__post_init__()
        for name in ('fallback_harm', 'fallback_rights', 'fallback_consent', 'fallback_reversibility'):
            unit(getattr(self, name), name)
