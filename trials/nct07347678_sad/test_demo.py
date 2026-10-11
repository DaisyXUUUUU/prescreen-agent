"""Author-designed technical checks, not independent clinical reference labels."""
import copy,json,unittest,hashlib
from pathlib import Path
from engine import evaluate
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8'))

class DemoTests(unittest.TestCase):
    def setUp(self):
        self.spec=read(HERE/'rules/sad-1.0.0.json');self.b=read(HERE/'data/cases/SAD01.json');self.c=read(HERE/'data/context/SAD01.json')
    def obs(self,code):
        return next(e['resource'] for e in self.b['entry'] if any(c.get('code')==code for c in e['resource'].get('code',{}).get('coding',[])))
    def answer(self,key,val):
        qr=next(e['resource'] for e in self.b['entry'] if e['resource']['resourceType']=='QuestionnaireResponse')
        item=next((x for x in qr['item'] if x['linkId']==key),None)
        typ='valueBoolean' if isinstance(val,bool) else 'valueDecimal' if isinstance(val,(float,int)) else 'valueString'
        if item: item['answer']=[{typ:val}]
        else: qr['item'].append({'linkId':key,'answer':[{typ:val}]})
    def outcome(self,cid):return next(r for r in evaluate(self.b,self.c,self.spec)['criteria'] if r['criterion_id']==cid)
    def test_eight_cases(self):
        expected=['passes_evaluated_criteria','fails_evaluated_criteria','fails_evaluated_criteria','passes_evaluated_criteria','fails_evaluated_criteria','pending','review','fails_evaluated_criteria']
        for i,decision in enumerate(expected,1):
            with self.subTest(case=i):
                result=evaluate(read(HERE/f'data/cases/SAD{i:02d}.json'),read(HERE/f'data/context/SAD{i:02d}.json'),self.spec)
                self.assertEqual(result['decision'],decision)
                self.assertEqual(len(result['criteria']),11)
                self.assertTrue(result['manual_review_required'])
    def test_numeric_boundaries(self):
        for code,cid,tests in [('39156-5','I1',[(18,'met'),(35,'met'),(35.1,'not_met')]),
            ('18262-6','I2',[(70,'met'),(69.9,'not_met')]),('43583-4','I3',[(25,'met'),(24.9,'not_met')]),
            ('2571-8','I4',[(399.9,'met'),(400,'not_met')]),('4548-4','E2',[(6.49,'not_met'),(6.5,'met')])]:
            for value,status in tests:
                with self.subTest(code=code,value=value):
                    self.obs(code)['valueQuantity']['value']=value;self.assertEqual(self.outcome(cid)['status'],status)
    def test_age(self):
        p=next(e['resource'] for e in self.b['entry'] if e['resource']['resourceType']=='Patient')
        for birth,status in [('1961-10-09','met'),('1960-10-09','not_met'),('2008-10-09','met'),('2008-10-10','not_met')]:
            with self.subTest(birth=birth):p['birthDate']=birth;self.assertEqual(self.outcome('AGE')['status'],status)
    def test_missing_fasting(self):
        sp=next(e['resource'] for e in self.b['entry'] if e['resource']['resourceType']=='Specimen');sp['collection'].pop('fastingStatusDuration')
        self.assertEqual(self.outcome('I2')['status'],'unknown');self.assertEqual(self.outcome('I4')['status'],'unknown')
    def test_lpa_unit(self):
        self.obs('43583-4')['valueQuantity']['code']='mg/dL';self.assertEqual(self.outcome('I3')['status'],'unknown')
    def test_ulp_and_or(self):
        self.obs('1742-6')['valueQuantity']['value']=60;self.obs('1920-8')['valueQuantity']['value']=52.5
        self.assertEqual(self.outcome('E1')['status'],'not_met')
        self.obs('1742-6')['valueQuantity']['value']=60.1;self.obs('1920-8').pop('referenceRange')
        self.assertEqual(self.outcome('E1')['status'],'met')
    def test_missing_ulp(self):
        self.obs('1742-6').pop('referenceRange');self.assertEqual(self.outcome('E1')['status'],'unknown')
    def test_smoking(self):
        self.answer('current_smoker',True);self.answer('smoking_pattern','current_continuous')
        for day,week,status in [(2,10,'not_met'),(3,10,'met'),(2,11,'met')]:
            self.answer('cigarettes_day',day);self.answer('cigarettes_week',week);self.assertEqual(self.outcome('E3')['status'],status)
        self.answer('smoking_pattern','intermittent');self.assertEqual(self.outcome('E3')['status'],'unknown')
    def test_incomplete_history(self):
        for prefix,cid in [('smoking','E3'),('advanced','E4'),('lipid','E5')]:
            self.answer(prefix+'_complete',False);self.assertEqual(self.outcome(cid)['status'],'unknown')
    def test_exposure_dates(self):
        for prefix,cid,values in [('lipid','E5',[('2026-09-09','met'),('2026-09-08','not_met'),('2026-10-10','unknown')]),
            ('advanced','E4',[('2025-10-09','met'),('2025-10-08','not_met')])]:
            self.answer(prefix+'_exposure',True)
            for when,status in values:
                self.answer(prefix+'_last_use',when);self.assertEqual(self.outcome(cid)['status'],status)
    def test_conflict(self):
        r=copy.deepcopy(self.obs('18262-6'));r['id']='conflict';r['valueQuantity']['value']=120
        self.b['entry'].append({'fullUrl':'urn:uuid:conflict','resource':r})
        result=self.outcome('I2');self.assertEqual(result['status'],'unknown');self.assertTrue(result['conflict'])
    def test_other_patient(self):
        self.obs('18262-6')['subject']['reference']='urn:uuid:other';self.assertEqual(self.outcome('I2')['status'],'unknown')
    def test_poc_rejected(self):
        self.c['cohort']='POC'
        with self.assertRaises(ValueError):evaluate(self.b,self.c,self.spec)
    def test_manual_remains(self):self.assertEqual(self.outcome('I5')['status'],'unknown')
    def test_invalid_numeric(self):
        for x in [-1,float('nan')]:
            self.obs('18262-6')['valueQuantity']['value']=x;self.assertEqual(self.outcome('I2')['status'],'unknown')
    def test_evidence_resolves(self):
        for p in (HERE/'data/context').glob('*.json'):
            c=read(p);b=read(HERE/'data'/c['FHIR_file']);idx={e['resource']['resourceType']+'/'+e['resource']['id'] for e in b['entry']}
            for row in evaluate(b,c,self.spec)['criteria']:
                if row['status']!='unknown':self.assertTrue(row['evidence'])
                for e in row['evidence']:self.assertIn(e['resource_ref'],idx)
    def test_originals_unchanged(self):
        for c in read(HERE/'data/case_manifest.json')['cases']:
            p=HERE/c['source_file'];self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),c['source_sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
