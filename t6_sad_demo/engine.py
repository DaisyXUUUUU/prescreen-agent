"""Deterministic SAD-only evaluation over explicitly scoped local FHIR records."""
from datetime import date,datetime,timedelta
import calendar
import math

class DataIssue(Exception):
    def __init__(self,reason,evidence=None,conflict=False):
        self.reason=reason;self.evidence=evidence or [];self.conflict=conflict

def subtract_months(d,n):
    y,m=divmod(d.year*12+d.month-1-n,12)
    return d.replace(year=y,month=m+1,day=min(d.day,calendar.monthrange(y,m+1)[1]))

class Reader:
    def __init__(self,bundle,ctx):
        self.ctx=ctx;self.trace=[]
        self.index={e['fullUrl']:e['resource'] for e in bundle['entry']}
        self.patient='urn:uuid:'+ctx['patient_id'];self.enc='urn:uuid:'+ctx['encounter_id']
        self.at=datetime.fromisoformat(ctx['screening_at']);self.day=self.at.date()
    def evidence(self,r,path,value):
        return {'resource_ref':r['resourceType']+'/'+r['id'],'field':path,'value':value,'patient_id':self.ctx['patient_id']}
    def observation(self,code,unit,fast=False):
        found=[r for r in self.index.values() if r['resourceType']=='Observation' and
            r.get('subject',{}).get('reference')==self.patient and r.get('encounter',{}).get('reference')==self.enc and
            any(c.get('code')==code and c.get('system')=='http://loinc.org' for c in r.get('code',{}).get('coding',[]))]
        self.trace.append({'tool':'local_fhir_query','type':'Observation','code':code,'patient':self.patient,'encounter':self.enc,'count':len(found)})
        ev=[self.evidence(r,'valueQuantity',r.get('valueQuantity')) for r in found]
        if not found: raise DataIssue('No matching screening observation; no negative inference',ev)
        if len(found)!=1: raise DataIssue('Multiple candidate results; selection unresolved',ev,True)
        r=found[0];q=r.get('valueQuantity',{})
        if r.get('status')!='final': raise DataIssue('Result is not final',ev)
        try:
            obsdate=datetime.fromisoformat(r['effectiveDateTime'])
            if obsdate.date()!=self.day or obsdate>self.at: raise ValueError()
        except (KeyError,ValueError,TypeError): raise DataIssue('Sampling time is outside bound screening context or missing',ev)
        if q.get('code')!=unit or not isinstance(q.get('value'),(int,float)) or isinstance(q.get('value'),bool):
            raise DataIssue('Unsupported/missing unit or numeric value',ev)
        if not math.isfinite(q['value']) or q['value']<0 or (code=='39156-5' and q['value']==0):
            raise DataIssue('Invalid/nonfinite measurement',ev)
        ev.append(self.evidence(r,'effectiveDateTime',r['effectiveDateTime']))
        if fast:
            sp=self.index.get(r.get('specimen',{}).get('reference'),{})
            duration=sp.get('collection',{}).get('fastingStatusDuration',{})
            if sp.get('subject',{}).get('reference')!=self.patient or duration.get('code')!='h' or duration.get('value',0)<=0:
                raise DataIssue('Fasting state not confirmed',ev)
            ev.append(self.evidence(sp,'collection.fastingStatusDuration',duration))
        return q['value'],ev,r
    def history(self):
        r=self.index.get('urn:uuid:'+self.ctx['history_id'],{})
        self.trace.append({'tool':'local_fhir_query','type':'QuestionnaireResponse','id':self.ctx['history_id']})
        if r.get('subject',{}).get('reference')!=self.patient or r.get('encounter',{}).get('reference')!=self.enc or r.get('status')!='completed':
            raise DataIssue('Missing or mismatched completed screening history')
        answers={};ev=[]
        for item in r.get('item',[]):
            values=[v for a in item.get('answer',[]) for k,v in a.items() if k.startswith('value')]
            if len(values)!=1: continue
            key=item['linkId']
            if key in answers: raise DataIssue('Duplicate conflicting questionnaire fields',ev,True)
            answers[key]=values[0]
            ev.append(self.evidence(r,'item.'+key,values[0]))
        return answers,ev

def evaluate(bundle,ctx,spec):
    if ctx['cohort']!='SAD' or ctx['trial_id']!=spec['trial_id'] or spec['cohort']!='SAD':
        raise ValueError('This rule pack supports NCT07347678 SAD only; do not apply it to POC.')
    rd=Reader(bundle,ctx);pred={r['id']:r['predicate'] for r in spec['rules']};rows=[]
    def record(cid,func,manual=False):
        try:
            response=func()
            value,ev,reason=response[:3]
            result={'status':'met' if value else 'not_met','reason':reason,'evidence':ev,'conflict':response[3] if len(response)>3 else False}
        except DataIssue as e: result={'status':'unknown','reason':e.reason,'evidence':e.evidence,'conflict':e.conflict}
        rows.append({'criterion_id':cid,'type':'metadata' if cid=='AGE' else 'inclusion' if cid[0]=='I' else 'exclusion','manual':manual,**result})
    def age():
        p=rd.index.get(rd.patient,{})
        rd.trace.append({'tool':'local_fhir_query','type':'Patient','id':ctx['patient_id']})
        try: birth=date.fromisoformat(p['birthDate'])
        except (ValueError,KeyError): raise DataIssue('Birth date missing or not a full date')
        years=rd.day.year-birth.year-((rd.day.month,rd.day.day)<(birth.month,birth.day))
        return spec['age_metadata']['minimum']<=years<=spec['age_metadata']['maximum'],[rd.evidence(p,'birthDate',p['birthDate'])],f'Age at screening={years}'
    record('AGE',age)
    def numeric(cid,code,unit,fn,fast=False):
        def perform():
            v,ev,_=rd.observation(code,unit,fast)
            return fn(v),ev,f'{code}={v} {unit}; predicate from {spec["version"]}/{cid}'
        record(cid,perform)
    numeric('I1','39156-5','kg/m2',lambda x:pred['I1']['lower']<=x<=pred['I1']['upper'])
    numeric('I2','18262-6','mg/dL',lambda x:x>=pred['I2']['lower'],True)
    numeric('I3','43583-4','nmol/L',lambda x:x>=pred['I3']['lower'])
    numeric('I4','2571-8','mg/dL',lambda x:x<pred['I4']['upper'],True)
    def manual(): raise DataIssue('Investigator assessment of clinically significant hepatic/renal abnormality required; ALT/AST alone insufficient')
    record('I5',manual,True)
    def liver():
        vals=[];ev=[];problems=[]
        for code in ['1742-6','1920-8']:
            try:
                v,e,r=rd.observation(code,'U/L');ev+=e
                ranges=r.get('referenceRange',[])
                if len(ranges)!=1: raise DataIssue('Missing or ambiguous ULN',ev)
                high=ranges[0].get('high',{})
                if high.get('code')!='U/L' or not isinstance(high.get('value'),(int,float)) or high['value']<=0:
                    raise DataIssue('Missing/invalid ULN',ev)
                ev.append(rd.evidence(r,'referenceRange[0].high',high))
                vals.append(v>pred['E1']['ULN_multiplier']*high['value'])
            except DataIssue as e: problems.append(e)
        if any(vals): return True,ev+sum([p.evidence for p in problems],[]),'At least one known ALT/AST branch exceeds 1.5×ULN; unresolved other-branch evidence retained',any(p.conflict for p in problems)
        if problems: raise DataIssue('; '.join(p.reason for p in problems),ev+sum([p.evidence for p in problems],[]),any(p.conflict for p in problems))
        return False,ev,'Both ALT and AST at or below 1.5×ULN'
    record('E1',liver)
    numeric('E2','4548-4','%',lambda x:x>=pred['E2']['value'])
    def covered(prefix,months=None,days=None):
        a,ev=rd.history()
        ev=[e for e in ev if e['field'].startswith('item.'+prefix+'_') or (prefix=='smoking' and e['field'] in ['item.current_smoker','item.cigarettes_day','item.cigarettes_week'])]
        start=subtract_months(rd.day,months) if months else rd.day-timedelta(days=days)
        try:
            if a[prefix+'_complete'] is not True or date.fromisoformat(a[prefix+'_window_start'])>start or date.fromisoformat(a[prefix+'_window_end'])<rd.day:
                raise ValueError()
        except (KeyError,ValueError,TypeError): raise DataIssue('Explicit history coverage/completeness missing for '+prefix,ev)
        return a,ev,start
    def smoke():
        a,ev,_=covered('smoking',months=pred['E3']['lookback_calendar_months'])
        pattern=a.get('smoking_pattern');current=a.get('current_smoker')
        day=a.get('cigarettes_day');week=a.get('cigarettes_week')
        if pattern=='none_in_window' and current is False and day==0 and week==0:
            return False,ev,'Explicit report of no smoking throughout three-calendar-month window'
        if pattern!='current_continuous' or current is not True:
            raise DataIssue('Unclear/intermittent smoking pattern requires review',ev)
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and v>=0 for v in [day,week]):
            raise DataIssue('Daily/weekly amount missing or invalid',ev)
        return day>pred['E3']['daily'] or week>pred['E3']['weekly'],ev,'Current continuous smoking; compare reported day/week amounts'
    record('E3',smoke)
    def exposure(prefix,cid):
        a,ev,start=covered(prefix,months=pred[cid].get('lookback_calendar_months'),days=pred[cid].get('lookback_days'))
        reported=a.get(prefix+'_exposure')
        if reported is False: return False,ev,'Explicit negative synthetic interview covering entire window; self-report limitation retained'
        if reported is not True: raise DataIssue('Exposure response missing',ev)
        try: last=date.fromisoformat(a[prefix+'_last_use'])
        except (KeyError,ValueError,TypeError): raise DataIssue('Positive exposure without usable date',ev)
        if last>rd.day: raise DataIssue('Future date cannot establish prior use',ev)
        return start<=last<=rd.day,ev,'Last reported class exposure compared to inclusive demo window'
    record('E4',lambda:exposure('advanced','E4'))
    record('E5',lambda:exposure('lipid','E5'))
    automatic=[r for r in rows if not r['manual']]
    failed=[r['criterion_id'] for r in automatic if (r['type']!='exclusion' and r['status']=='not_met') or (r['type']=='exclusion' and r['status']=='met')]
    conflict=any(r['conflict'] for r in rows)
    decision='fails_evaluated_criteria' if failed else 'review' if conflict else 'pending' if any(r['status']=='unknown' for r in automatic) else 'passes_evaluated_criteria'
    return {'case_id':ctx['case_id'],'patient_id':ctx['patient_id'],'trial_id':spec['trial_id'],'cohort':'SAD',
        'rule_version':spec['version'],'decision':decision,'failed_criteria':failed,'manual_review_required':True,
        'complete_eligibility':'not_determined','conflict':conflict,'criteria':rows,'tool_trace':rd.trace,
        'scope_note':'Designed synthetic study records only; no full-chart or clinical eligibility claim.'}
