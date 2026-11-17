"""Only numeric enclosure evidence is changed; no private imports."""
from experiments.causal_refusal_20261018.controller import CausalController
from .public import bound_dossier

VARIANTS=('current','numeric_set','bound_verified','rule_bound_verified')


class BoundController(CausalController):
    def __init__(self,variant,params):
        if variant not in VARIANTS:raise ValueError('unregistered variant')
        super().__init__({'bound_verified':'numeric_set','rule_bound_verified':'rule_verified'}.get(variant,variant),params)
        self.bound_variant=variant
        self.counts.update(bound_checks=0,calibration_point_checks=0)

    def dossier(self):
        if self.bound_variant not in ('bound_verified','rule_bound_verified'):return super().dossier()
        self.counts['evidence_resolutions']+=1;self.counts['claim_inspections']+=len(self.packet.claims)
        d=bound_dossier(self.packet)
        for k,v in d['bound_counts'].items():self.counts[k]+=v
        self.counts['numeric_domain_pairs']+=sum(x['checked_pairs'] for x in d['numeric_proofs'])
        return d
