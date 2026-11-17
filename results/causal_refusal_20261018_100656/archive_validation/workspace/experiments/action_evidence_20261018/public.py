"""Public claims only: no physical world, evaluator, labels or future outcomes."""
from dataclasses import dataclass,replace
from moral_agent.models import unit

SOURCES={'consent':('owner','registry'),'harm':('lab','inspector'),
         'reversibility':('lab','inspector'),'available':('resource',)}


@dataclass(frozen=True)
class Claim:
    action: str
    revision: str
    subject: str
    event: str
    axis: str
    value: bool|float
    source: str
    confidence: float
    issued: int
    expires: int

    def __post_init__(self):
        if self.axis not in SOURCES:raise ValueError('unknown evidence axis')
        unit(self.confidence,'confidence')
        if self.axis in ('consent','available'):
            if not isinstance(self.value,bool):raise ValueError('boolean claim required')
        else:unit(self.value,self.axis)
        if self.expires<self.issued:raise ValueError('invalid validity interval')


@dataclass(frozen=True)
class Scope:
    action: str
    revision: str
    consent_subjects: tuple[str,...]
    event_subjects: tuple[tuple[str,str],...]
    coverage_complete: bool=True

    def __post_init__(self):
        if not self.consent_subjects or not self.event_subjects:raise ValueError('nonempty scope required')
        if len(set(self.consent_subjects))!=len(self.consent_subjects):raise ValueError('duplicate subject')
        if len(set(self.event_subjects))!=len(self.event_subjects):raise ValueError('duplicate event scope')


@dataclass(frozen=True)
class Packet:
    scope: Scope
    now: int
    claims: tuple[Claim,...]
    disputed: bool=False


def required_keys(scope):
    return [('available','resource','availability')]+[
        ('consent',s,'permission') for s in scope.consent_subjects]+[
        (axis,subject,event) for event,subject in scope.event_subjects for axis in ('harm','reversibility')]


def resolve(packet,*,consent=True,side_effects=True):
    """Conservative conjunction with explicit missing/conflicting provenance."""
    scope=packet.scope;keys=required_keys(scope);slots={k:[] for k in keys};rejected=[]
    for i,c in enumerate(packet.claims):
        key=(c.axis,c.subject,c.event)
        reason=( 'action_or_revision' if (c.action,c.revision)!=(scope.action,scope.revision) else
                 'scope' if key not in slots else 'time' if not c.issued<=packet.now<=c.expires else
                 'source_or_confidence' if c.source not in SOURCES[c.axis] or c.confidence<.8 else None)
        if reason:rejected.append(dict(index=i,reason=reason))
        else:slots[key].append((i,c.value))
    values={};unknown=[];prohibited=[];details=[]
    for key,observations in slots.items():
        unique=sorted(set(v for _,v in observations));status='known' if len(unique)==1 else 'missing' if not unique else 'conflicting'
        values[key]=unique[0] if status=='known' else None
        details.append(dict(axis=key[0],subject=key[1],event=key[2],status=status,
                            values=unique,claim_indices=[i for i,_ in observations]))
        used=key[0]=='available' or (key[0]=='consent' and consent) or (key[0] in ('harm','reversibility') and side_effects)
        if used and status!='known':unknown.append('/'.join(key))
    if not scope.coverage_complete:unknown.append('coverage')
    if packet.disputed:unknown.append('disputed_authority')
    available=values[('available','resource','availability')]
    if available is False:prohibited.append('unavailable')
    consents={s:values[('consent',s,'permission')] for s in scope.consent_subjects}
    if consent:
        prohibited.extend('consent_denied:'+s for s,v in consents.items() if v is False)
    events=[]
    for event,subject in scope.event_subjects:
        h=values[('harm',subject,event)];r=values[('reversibility',subject,event)]
        events.append(dict(event=event,subject=subject,harm=h,reversibility=r))
        if side_effects and h is not None and (h>=.5 or (h>=.4 and r is not None and r<=.2)):
            prohibited.append('side_effect:'+event+':'+subject)
    status='BLOCK' if prohibited else 'ASK_HUMAN' if unknown else 'ALLOW'
    if packet.disputed:status='ASK_HUMAN'
    return dict(status=status,available=available,consents=consents,events=events,
                unknown=unknown,prohibited=prohibited,details=details,rejected=rejected)


def projection(evidence,packet,strict=False,*,consent=True,side_effects=True):
    """Common legacy adapter versus validated action/subject/event projection."""
    if not strict:
        changes={}
        names={'available':'alternative','consent':'fallback_consent','harm':'fallback_harm','reversibility':'fallback_reversibility'}
        for c in packet.claims:
            changes[names[c.axis]]=(0. if c.value else .9) if c.axis=='consent' else c.value
        return replace(evidence,**changes)
    d=resolve(packet,consent=consent,side_effects=side_effects)
    return replace(evidence,alternative=d['available'] is True,
        fallback_consent=.9 if consent and any(v is False for v in d['consents'].values()) else 0.,
        fallback_harm=max([0.,*[e['harm'] for e in d['events'] if e['harm'] is not None]]) if side_effects else 0.,
        fallback_reversibility=min([.95,*[e['reversibility'] for e in d['events'] if e['reversibility'] is not None]]) if side_effects else .95)
