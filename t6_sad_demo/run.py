"""Run all SAD cases and deliver local evidence-linked outputs. No model/AWS call."""
import hashlib,json
from collections import Counter
from html import escape
from pathlib import Path
from engine import evaluate
HERE=Path(__file__).resolve().parent
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def main():
    spec=read(HERE/'rules/sad-1.0.0.json');manifest=read(HERE/'rules/manifest.json')
    assert hashlib.sha256((HERE/'rules/sad-1.0.0.json').read_bytes()).hexdigest()==manifest['sha256'],'Rule version changed'
    assert hashlib.sha256((HERE/'source/NCT07347678.json').read_bytes()).hexdigest()==manifest['source_sha256'],'Source snapshot changed'
    for case in read(HERE/'data/case_manifest.json')['cases']:
        for path,key in [(HERE/'data/cases'/(case['case_id']+'.json'),'case_sha256'),(HERE/'data/context'/(case['case_id']+'.json'),'context_sha256')]:
            assert hashlib.sha256(path.read_bytes()).hexdigest()==case[key],f'Input changed: {path}'
    reports=[]
    for path in sorted((HERE/'data/context').glob('*.json')):
        context=read(path);reports.append(evaluate(read(HERE/'data'/context['FHIR_file']),context,spec))
    out=HERE/'outputs';out.mkdir(exist_ok=True)
    queue=[{'case_id':r['case_id'],'patient_id':r['patient_id'],**c} for r in reports for c in r['criteria'] if c['status']=='unknown' or c['conflict']]
    counts=dict(Counter(r['decision'] for r in reports))
    summary={'cases':len(reports),'rule_evaluations':sum(len(r['criteria']) for r in reports),
        'decision_counts':counts,'manual_review_cases':sum(r['manual_review_required'] for r in reports),
        'complete_eligibility_cases':0,'human_ground_truth_reviewed':False,'implementation':'local deterministic FHIR adapter/evaluator; no LLM agent yet'}
    for name,data in [('prescreening_log',reports),('exception_queue',queue),('summary',summary)]:
        (out/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# T6 SAD: local pre-screening run','',
       '8 purpose-built synthetic cases, 10 criteria plus the age constraint. Passing the computed part is not complete eligibility; I5 stays with the investigator in every case. There is no independent human ground truth, so no clinical accuracy can be reported.','',
       'Result: '+json.dumps(counts,ensure_ascii=False),'']
    for r in reports:
        lines += [f"## {r['case_id']} · {r['decision']}",'',f"Failed criteria: {', '.join(r['failed_criteria']) or 'none'}; human review: required.",'']
        for c in r['criteria']:
            refs=', '.join(e['resource_ref'] for e in c['evidence'])
            lines += [f"- {c['criterion_id']}: {c['status']}. {c['reason']}"+(f' Evidence: {refs}' if refs else '')]
        lines+=['']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    html='<html lang="en"><meta charset="utf-8"><title>T6 SAD pre-screening</title><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px;line-height:1.7}article{border-top:1px solid gray;padding:16px 0}h1{font-size:24px}summary{cursor:pointer}</style><h1>T6 SAD · local pre-screening log</h1><p>Passing the computed part is not complete eligibility. All 8 cases need human I5 review; this page reports no clinical accuracy.</p><p>'+escape(str(counts))+'</p>'
    for r in reports:
        html+=f"<article><h2>{r['case_id']} · {r['decision']}</h2>"
        for c in r['criteria']:
            html+=f"<details><summary>{c['criterion_id']} · {c['status']}</summary><p>{escape(c['reason'])}</p><pre style='white-space:pre-wrap'>{escape(json.dumps(c['evidence'],ensure_ascii=False,indent=2))}</pre></details>"
        html+='</article>'
    (out/'report.html').write_text(html+'</html>',encoding='utf-8')
    # Successful local delivery requires files to exist and parse.
    assert len(read(out/'prescreening_log.json'))==8 and len(read(out/'exception_queue.json'))>=8
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
