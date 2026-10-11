"""Export a blank, source-linked annotation sheet; never derive truth from engine outputs."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config
from src.engine import sad_adapter as sa


def main():
    out = ROOT/'out/independent-review'
    out.mkdir(parents=True, exist_ok=True)
    sheet = out/'labels-to-review.csv'
    if sheet.exists():
        with sheet.open(newline='', encoding='utf-8-sig') as f:
            if any(any(row.get(k, '').strip() for k in ('expected','reviewer','reviewed_at','source_evidence','reason'))
                   for row in csv.DictReader(f)):
                raise SystemExit('Refusing to overwrite an annotation sheet containing reviewer work.')
    cases = sa.load_cases() + sa.load_cases(config.DATA_DIR/'extended_cases/cases')
    predicates = [p for p in sa.predicates(sa.load_spec()) if p['computable']]
    with (out/'labels-to-review.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['patient_id','criterion_id','expected','reviewer','reviewed_at','source_evidence','reason'])
        for case in cases:
            for p in predicates:
                writer.writerow([case.case_id,p['criterion_id'],'','','','',''])
            writer.writerow([case.case_id,'PATIENT','','','','',''])
    # Source evidence only: omit design labels, purpose text and engine verdicts from the pack.
    (out/'source-cases.json').write_text(json.dumps([
        {'case_id':c.case_id,'screening_at':c.ctx['screening_at'],'bundle':c.bundle} for c in cases],indent=2),encoding='utf-8')
    (out/'criteria.json').write_text(json.dumps([
        {'criterion_id':p['criterion_id'],'type':p['type'],'source_text':p['source_text'],'compiled_rule':p['rule']}
        for p in predicates],indent=2),encoding='utf-8')
    (out/'README.md').write_text(
        '# Independent review pack - NOT completed labels\n\n'
        '58 synthetic cases; 580 computable criterion rows and 58 patient rows. Expected results are intentionally blank.\n'
        'A reviewer independent of the implementation must inspect source-cases.json and criteria.json, document evidence and sign each row.\n'
        'Review at least 20 complete patients, including every computable criterion. Do not copy engine outputs or design_labels.csv.\n'
        'Criterion values: met / not_met / unknown. Patient values: eligible / not_eligible / undetermined. I5 remains investigator review.\n'
        'Clarify EXT11 smoking (1-2/day gives 7-14/week) and EXT43 calculated code paired with a direct method.\n'
        'Confirm the synthetic LDL method policy and any fasting upper-duration handling with the rule owner.\n'
        'Keep reviewer, timestamp, source evidence and rationale. Export only adjudicated met/not_met criteria and eligible/not_eligible patient rows '
        'to patient_id,criterion_id,expected for evaluation. Preserve unknown/undetermined rows separately and report their count; never convert them to negative labels.\n',encoding='utf-8')
    print(f'Prepared blank review pack: {out}; independent review is still pending.')


if __name__ == '__main__':
    main()
