"""Prepare a versioned SAD specification and deliberately designed FHIR test cases.

Synthetic study records reuse only Synthea Patient demographics. Full Synthea
histories remain in data/raw and are NOT represented as completely screened.
"""
import hashlib,json,uuid
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
NS='https://example.org/t6-sad-demo'
SCREEN='2026-10-09'
AT=SCREEN+'T09:00:00-04:00'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def concept(code,text,system='http://loinc.org'): return {'coding':[{'system':system,'code':code,'display':text}]}
def month_start(d,months):
    import calendar
    year,month=divmod(d.year*12+d.month-1-months,12)
    return d.replace(year=year,month=month+1,day=min(d.day,calendar.monthrange(year,month+1)[1]))

def main():
    source=HERE/'source/NCT07347678.json'
    study=json.loads(source.read_text(encoding='utf-8'))['protocolSection']
    text=study['eligibilityModule']['eligibilityCriteria']
    lines=[x[2:] for x in text.splitlines() if x.startswith('* ')]
    assert len(lines)==10
    definitions=[
        ('I1','BMI',{'lower':18,'upper':35,'inclusive':True,'unit':'kg/m2'}),
        ('I2','fasting LDL-C',{'lower':70,'inclusive':True,'unit':'mg/dL','cohort':'SAD'}),
        ('I3','Lp(a)',{'lower':25,'inclusive':True,'unit':'nmol/L','cohort':'SAD'}),
        ('I4','fasting TG',{'upper':400,'inclusive':False,'unit':'mg/dL'}),
        ('I5','clinically significant hepatic/renal abnormality',{'mode':'manual_review','default':'unknown'}),
        ('E1','ALT or AST',{'operator':'>','ULN_multiplier':1.5,'logical_operator':'OR'}),
        ('E2','HbA1c',{'operator':'>=','value':6.5,'unit':'%'}),
        ('E3','current regular smoking',{'daily_operator':'>','daily':2,'weekly_operator':'>','weekly':10,'logical_operator':'OR','lookback_calendar_months':3}),
        ('E4','advanced therapies',{'classes':['siRNA','ASO','cell and gene therapy','CRISPR'],'lookback_calendar_months':12}),
        ('E5','prescription lipid-lowering medication',{'class':'all prescription lipid-lowering agents; examples are non-exhaustive','lookback_days':30})]
    spec={'version':'1.0.0','trial_id':'NCT07347678','cohort':'SAD','source_sha256':sha(source),
       'source_last_update':study['statusModule']['lastUpdatePostDateStruct']['date'],
       'source_saved_date':'2026-10-09','source_download_exact_time':None,
       'scope':'local synthetic pre-screening demo, no verified full protocol or independent clinical signoff',
       'age_metadata':{'minimum':18,'maximum':65,'inclusive':True,'anchor':'screening'},
       'rules':[{'id':cid,'type':'inclusion' if cid[0]=='I' else 'exclusion','concept':name,'predicate':logic,'source_text':raw}
          for (cid,name,logic),raw in zip(definitions,lines)],
       'demo_policies':['Screening is one explicitly bound encounter; BMI endpoints taken as inclusive.',
         'Calendar-month/day windows include both endpoints in this demo; exact clinical protocol confirmation remains outstanding.',
         'Only no-smoking-throughout-window or current-continuous-smoking patterns are automated; intermittent/unclear histories return unknown.',
         'Negative exposure requires explicit completed synthetic screening interview and coverage spanning the entire requested window; absent records alone never mean negative.',
         'Questionnaire values are patient-reported synthetic evidence, not proven adherence or independently verified medical history.',
         'Conflicting observations require review. Unsupported units, missing fasting/method/ULN and missing coverage return unknown.',
         'I5 always remains manual: normal ALT/AST cannot establish absence of all clinically significant hepatic/renal abnormalities.',
         'All supplied cases are authored examples, not an unbiased sample or independently labeled clinical test set.'],
       'freeze_time_utc':datetime.now(timezone.utc).isoformat()}
    specpath=HERE/'rules/sad-1.0.0.json'
    if specpath.exists(): raise SystemExit('Specification already frozen; rerun run.py, not prepare.py. New definitions require a new version.')
    write(specpath,spec)
    paths=sorted((HERE/'data/raw/fhir').glob('*.json'))
    patients=[]
    for p in paths:
        b=json.loads(p.read_text(encoding='utf-8'))
        ps=[e['resource'] for e in b['entry'] if e['resource']['resourceType']=='Patient']
        if len(ps)==1: patients.append((p,ps[0]))
    assert len(patients)==8
    manifest=[]
    for i,(raw,patient) in enumerate(patients,1):
        sid=f'SAD{i:02d}'; resources=[patient]
        def add(typ,key,**values):
            r={'resourceType':typ,'id':str(uuid.uuid5(uuid.NAMESPACE_URL,NS+'/'+sid+'/'+key)),
               'meta':{'tag':[{'system':NS,'code':'authored-synthetic-screening'}]},**values}
            resources.append(r); return r
        def ref(r): return {'reference':'urn:uuid:'+r['id']}
        enc=add('Encounter','screening',status='finished',**{'class':{'system':'http://terminology.hl7.org/CodeSystem/v3-ActCode','code':'AMB'}},
           subject=ref(patient),period={'start':AT,'end':SCREEN+'T10:00:00-04:00'},type=[{'text':'SAD study screening; synthetic'}])
        specimen=add('Specimen','serum',status='available',subject=ref(patient),type={'text':'Serum'},
             collection={'collectedDateTime':AT,'fastingStatusDuration':{'value':10,'unit':'hours','system':'http://unitsofmeasure.org','code':'h'}})
        vals={'bmi':22,'ldl':90,'lpa':40,'tg':150,'alt':25,'ast':25,'a1c':5.4}
        if i==2: vals['ldl']=69
        if i==3: vals['lpa']=24
        if i==4: vals.update(bmi=18,ldl=70,lpa=25,tg=399.9,alt=60,ast=52.5,a1c=6.4)
        if i==5: vals['a1c']=6.5
        codes={'bmi':('39156-5','BMI','kg/m2'),'ldl':('18262-6','LDL cholesterol','mg/dL'),
            'lpa':('43583-4','Lipoprotein(a) molar concentration','nmol/L'),'tg':('2571-8','Triglycerides','mg/dL'),
            'alt':('1742-6','Alanine aminotransferase','U/L'),'ast':('1920-8','Aspartate aminotransferase','U/L'),
            'a1c':('4548-4','Hemoglobin A1c','%')}
        for name,(code,label,unit) in codes.items():
            if i==6 and name=='lpa': continue
            if name=='bmi':
                ht=1.70; wt=round(vals['bmi']*ht*ht,4)
                bases=[]
                for k,c,v,u in [('height','8302-2',170,'cm'),('weight','29463-7',wt,'kg')]:
                    bases.append(add('Observation',k,status='final',code=concept(c,k),subject=ref(patient),encounter=ref(enc),effectiveDateTime=AT,
                        valueQuantity={'value':v,'unit':u,'system':'http://unitsofmeasure.org','code':u}))
            extras={}
            if name!='bmi': extras['specimen']=ref(specimen)
            else: extras['derivedFrom']=[ref(r) for r in bases]
            if name in ['alt','ast']:
                extras['referenceRange']=[{'high':{'value':40 if name=='alt' else 35,'unit':'U/L','system':'http://unitsofmeasure.org','code':'U/L'}}]
            if name=='ldl': extras['method']={'text':'Synthetic direct LDL laboratory result'}
            add('Observation',name,status='final',code=concept(code,label),subject=ref(patient),encounter=ref(enc),effectiveDateTime=AT,
                valueQuantity={'value':vals[name],'unit':unit,'system':'http://unitsofmeasure.org','code':unit},**extras)
        if i==7:
            add('Observation','conflicting-ldl',status='final',code=concept('18262-6','LDL cholesterol'),subject=ref(patient),
                encounter=ref(enc),effectiveDateTime=AT,specimen=ref(specimen),method={'text':'Synthetic direct LDL laboratory result'},
                valueQuantity={'value':110,'unit':'mg/dL','system':'http://unitsofmeasure.org','code':'mg/dL'})
        screen=date.fromisoformat(SCREEN)
        answers={
            'smoking_complete':True,'smoking_window_start':month_start(screen,3).isoformat(),'smoking_window_end':SCREEN,
            'current_smoker':i==8,'smoking_pattern':'current_continuous' if i==8 else 'none_in_window',
            'cigarettes_day':3 if i==8 else 0,'cigarettes_week':21 if i==8 else 0,
            'advanced_complete':True,'advanced_window_start':month_start(screen,12).isoformat(),'advanced_window_end':SCREEN,
            'advanced_exposure':False,'lipid_complete':True,'lipid_window_start':(screen-timedelta(days=30)).isoformat(),
            'lipid_window_end':SCREEN,'lipid_exposure':i==8,
            'liver_renal_significance':'Unknown — investigator assessment not supplied',
            'history_source':'Synthetic study interview only; background Synthea chart is not reconciled or treated as a complete negative history'}
        if i==8: answers.update(lipid_last_use=(screen-timedelta(days=10)).isoformat(),lipid_drug='atorvastatin (reported prescription lipid-lowering use)')
        items=[]
        for key,value in answers.items():
            typ='valueBoolean' if isinstance(value,bool) else 'valueDecimal' if isinstance(value,(float,int)) else 'valueDate' if key.endswith(('_start','_end','_use')) else 'valueString'
            items.append({'linkId':key,'text':key.replace('_',' '),'answer':[{typ:value}]})
        qr=add('QuestionnaireResponse','history',status='completed',subject=ref(patient),encounter=ref(enc),authored=AT,source=ref(patient),item=items)
        if i==8:
            add('MedicationStatement','reported-statin',status='completed',medicationCodeableConcept={'text':'atorvastatin'},subject=ref(patient),
                context=ref(enc),effectiveDateTime=answers['lipid_last_use'],informationSource=ref(patient),dateAsserted=AT,
                derivedFrom=[ref(qr)],note=[{'text':'Synthetic reported use for dyslipidemia; not an inferred prescription adherence event.'}])
        generator=add('Device','generator',status='active',deviceName=[{'name':'T6 synthetic scenario builder','type':'user-friendly-name'}])
        targets=[ref(r) for r in resources if r is not patient]
        add('Provenance','provenance',target=targets,recorded=datetime.now(timezone.utc).isoformat(),agent=[{'who':ref(generator)}],
            entity=[{'role':'source','what':{'identifier':{'system':NS+'/sha256','value':sha(raw)},'display':'Synthea Patient demographics only; remaining screening resources are authored fixtures'}}])
        bundle={'resourceType':'Bundle','type':'collection','entry':[{'fullUrl':'urn:uuid:'+r['id'],'resource':r} for r in resources]}
        target=HERE/'data/cases'/f'{sid}.json'
        write(target,bundle)
        write(HERE/'data/context'/f'{sid}.json',{'case_id':sid,'trial_id':'NCT07347678','cohort':'SAD','patient_id':patient['id'],
             'screening_at':AT,'encounter_id':enc['id'],'history_id':qr['id'],'FHIR_file':f'cases/{sid}.json',
             'data_scope':'Purpose-built study records using Synthea demographics; not the full longitudinal chart'})
        manifest.append({'case_id':sid,'source_file':raw.relative_to(HERE).as_posix(),'source_sha256':sha(raw),
            'patient_id':patient['id'],'case_sha256':sha(target),'context_sha256':sha(HERE/'data/context'/f'{sid}.json'),
            'patient_demographics_unchanged':True,'full_history_included':False})
    write(HERE/'data/case_manifest.json',{'seed':20261009,'clinician_seed':20261009,'synthea_version':'3.3.0',
        'age_generation_range':'18–65','simulation_end_date':SCREEN,'cases':manifest,
        'bias':'Cases deliberately cover boundaries/failures/missing/conflicting evidence; not a recruitment yield estimate.'})
    write(HERE/'rules/manifest.json',{'version':'1.0.0','sha256':sha(specpath),'source_sha256':sha(source)})
    print('Prepared SAD 1.0.0, 10 criteria + age metadata, 8 synthetic study cases.')

if __name__=='__main__': main()
