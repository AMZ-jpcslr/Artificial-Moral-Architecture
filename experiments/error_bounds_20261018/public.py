"""Public calibration evidence and a conditional enclosure certificate.

No private scenario, truth, evaluator or feedback is accessible here. The theorem
is conditional on the published instrument contract, authentic references and
honest acquisition lineage. Arithmetic verification cannot authenticate reality.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib,json,math
from experiments.action_evidence_20261018.public import Packet,SOURCES,resolve
from experiments.causal_refusal_20261018.controller import numeric_dossier

METHOD='grid_lipschitz_v1'
GRID=(0.,.25,.5,.75,1.)
# Fixed public acquisition specifications, not fitted to evaluation cases.
CONTRACT=dict(error_lipschitz=.08,reference_error=.002,repeatability=.01,
              drift_per_tick=.0002,max_age=50,temperature_min=10.,temperature_max=35.)
REGISTRY={s:dict(pipeline='acquisition-'+s,authority='reference-'+s,
                 lineage='independent-root-'+s) for s in ('lab','inspector')}


@dataclass(frozen=True)
class CalibrationPoint:
    reference: float
    reading: float
    reference_id: str


@dataclass(frozen=True)
class Certificate:
    id: str
    source: str
    axis: str
    method: str
    instrument: str
    authority: str
    lineage: str
    issued: int
    expires: int
    domain: tuple[float,float]
    temperature: tuple[float,float]
    points: tuple[CalibrationPoint,...]
    published_base_bound: float


@dataclass(frozen=True)
class Measurement:
    claim_digest: str
    certificate_id: str
    acquired: int
    temperature: float
    pipeline: str
    lineage: str
    published_error_bound: float


@dataclass(frozen=True)
class BoundPacket(Packet):
    certificates: tuple[Certificate,...]=()
    measurements: tuple[Measurement,...]=()


def claim_digest(claim):
    data={k:getattr(claim,k) for k in claim.__dataclass_fields__}
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def dec(x):return Decimal(str(x))


def base_bound(points):
    """Nearest grid point: |e(x)| <= max |e(x_i)| + L*max_gap/2.

    Add reference tolerance and bounded measurement noise. Monotone clipping to
    [0,1] cannot enlarge distance to a true value in that domain. This is NOT a
    statistical confidence interval inferred from a few calibration samples.
    """
    residual=max(abs(dec(p.reading)-dec(p.reference)) for p in points)
    gap=max(dec(b.reference)-dec(a.reference) for a,b in zip(points,points[1:]))
    return residual+dec(CONTRACT['error_lipschitz'])*gap/2+dec(CONTRACT['reference_error'])+dec(CONTRACT['repeatability'])


def check_measurement(claim,measurement,certificate,now):
    """Validate public scope and recompute the published deterministic bound."""
    reasons=[];s=claim.source;registry=REGISTRY.get(s)
    if registry is None:return dict(valid=False,reasons=['unregistered_source'])
    if certificate.source!=s or certificate.axis!=claim.axis:reasons.append('certificate_scope')
    if certificate.method!=METHOD:reasons.append('acquisition_method')
    if certificate.instrument!=s+'-'+claim.axis:reasons.append('instrument')
    if certificate.authority!=registry['authority']:reasons.append('reference_authority')
    if certificate.lineage!=registry['lineage'] or measurement.lineage!=registry['lineage']:reasons.append('independence_lineage')
    if measurement.pipeline!=registry['pipeline']:reasons.append('acquisition_pipeline')
    if measurement.claim_digest!=claim_digest(claim):reasons.append('claim_binding')
    if not(certificate.issued<=measurement.acquired==claim.issued<=now<=certificate.expires):reasons.append('validity')
    age=measurement.acquired-certificate.issued
    if not 0<=age<=CONTRACT['max_age']:reasons.append('calibration_age')
    if tuple(certificate.domain)!=(0.,1.):reasons.append('measurand_domain')
    if tuple(certificate.temperature)!=(CONTRACT['temperature_min'],CONTRACT['temperature_max']):reasons.append('calibration_context')
    if not math.isfinite(measurement.temperature) or not certificate.temperature[0]<=measurement.temperature<=certificate.temperature[1]:reasons.append('outside_context')
    points=certificate.points
    if tuple(p.reference for p in points)!=GRID:reasons.append('calibration_grid_coverage')
    if any(p.reference_id!=f"{registry['authority']}:{claim.axis}:{p.reference}" for p in points):reasons.append('reference_traceability')
    numbers=[certificate.published_base_bound,measurement.published_error_bound,*[p.reading for p in points]]
    if any(not math.isfinite(v) for v in numbers):reasons.append('nonfinite')
    if reasons:return dict(valid=False,reasons=reasons)
    calculated=base_bound(points)
    if dec(certificate.published_base_bound)<calculated:reasons.append('understated_base_bound')
    required=dec(certificate.published_base_bound)+dec(CONTRACT['drift_per_tick'])*age
    if dec(measurement.published_error_bound)<required:reasons.append('understated_measurement_bound')
    if not 0<=measurement.published_error_bound<=1:reasons.append('invalid_bound')
    bound=dec(measurement.published_error_bound);value=dec(claim.value)
    return dict(valid=not reasons,reasons=reasons,calculated_base=float(calculated),required_bound=float(required),
                lower=float(max(Decimal(0),value-bound)),upper=float(min(Decimal(1),value+bound)),
                lineage=measurement.lineage,source=s,bound=float(bound))


def bound_domains(packet):
    """Union envelope of verified intervals; never an unjustified intersection.

    Every usable numerical observation must have exactly one bound proof. Two
    independent registered acquisition/reference paths are required per slot.
    Contradictory certified intervals are unresolved even with good metadata.
    """
    d=resolve(packet);certs={};measurements={};out=[];checks=0;points=0
    for c in packet.certificates:certs.setdefault(c.id,[]).append(c)
    for m in packet.measurements:measurements.setdefault(m.claim_digest,[]).append(m)
    for detail in d['details']:
        if detail['axis'] not in ('harm','reversibility'):continue
        verified=[];issues=[]
        for index in detail['claim_indices']:
            claim=packet.claims[index];ms=measurements.get(claim_digest(claim),[])
            if len(ms)!=1:issues.append(dict(index=index,reason='missing_or_duplicate_binding'));continue
            cs=certs.get(ms[0].certificate_id,[])
            if len(cs)!=1:issues.append(dict(index=index,reason='missing_or_duplicate_certificate'));continue
            checks+=1;points+=len(cs[0].points);check=check_measurement(claim,ms[0],cs[0],packet.now)
            if not check['valid']:issues.extend(dict(index=index,reason=r) for r in check['reasons'])
            else:verified.append(dict(index=index,**check))
        if len({x['source'] for x in verified})<2 or len({x['lineage'] for x in verified})<2:
            issues.append(dict(index=None,reason='independent_paths_missing'))
        if verified and max(x['lower'] for x in verified)>min(x['upper'] for x in verified):
            issues.append(dict(index=None,reason='disjoint_certified_intervals'))
        valid=bool(verified) and not issues
        out.append(dict(axis=detail['axis'],subject=detail['subject'],event=detail['event'],valid=valid,
            observed=detail['values'],lower=min(x['lower'] for x in verified) if valid else None,
            upper=max(x['upper'] for x in verified) if valid else None,proofs=verified,issues=issues))
    return out,dict(bound_checks=checks,calibration_point_checks=points)


def bound_dossier(packet):
    d=numeric_dossier(packet);domains,counts=bound_domains(packet)
    by={(x['axis'],x['subject'],x['event']):x for x in domains}
    unknown=set(d['unknown']);events=[];proofs=[]
    for event in d['events']:
        name,subject=event['event'],event['subject'];h=by['harm',subject,name];r=by['reversibility',subject,name]
        if h['valid'] and r['valid']:
            safe=h['upper']<.5 and(h['upper']<.4 or r['lower']>.2)
            if safe:
                unknown.discard('/'.join(('harm',subject,name)));unknown.discard('/'.join(('reversibility',subject,name)))
            else:unknown.add('bound_crosses_constraint/'+subject+'/'+name)
            events.append(event|dict(harm=h['upper'],reversibility=r['lower']))
            proofs.append(dict(event=name,subject=subject,all_enclosed_values_safe=safe))
        else:
            unknown.add('unverified_bound/'+subject+'/'+name);events.append(event)
    status='BLOCK' if d['prohibited'] else 'ASK_HUMAN' if unknown else 'ALLOW'
    if packet.disputed:status='ASK_HUMAN'
    return d|dict(status=status,unknown=sorted(unknown),events=events,bound_domains=domains,bound_proofs=proofs,
                  bound_counts=counts,enclosure_contract='conditional deterministic calibration envelope')
