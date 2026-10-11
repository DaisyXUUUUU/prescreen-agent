"""Score the user-designated eight-case SAD reference without changing its labels."""
import argparse
import csv
import json
from pathlib import Path

CASE_IDS = {f'SAD{i:02}' for i in range(1, 9)}
CRITERIA = {'AGE', *(f'I{i}' for i in range(1, 6)), *(f'E{i}' for i in range(1, 6))}
DECISIONS = {'passes_evaluated_criteria': 'likely_eligible',
             'fails_evaluated_criteria': 'excluded', 'pending': 'pending', 'review': 'needs_review'}
DEFAULT_LABELS = Path(__file__).resolve().parents[1]/'data/ground_truth/sad_confirmed_labels_v1.csv'


def load_reference(path=DEFAULT_LABELS):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    expected = {}
    for row in rows:
        key = row['case_id'], row['criterion_id']
        value = row['ai_draft_expected'].strip()  # Original user-supplied column name, preserved.
        allowed = DECISIONS if key[1] == 'DECISION' else {'met','not_met','unknown'}
        if key in expected or value not in allowed:
            raise ValueError(f'duplicate or unsupported reference: {key}')
        expected[key] = value
    required = {(p,c) for p in CASE_IDS for c in CRITERIA | {'DECISION'}}
    if set(expected) != required:
        raise ValueError('reference must contain exactly SAD01-SAD08, each with 11 criteria and DECISION (96 rows)')
    return expected


def score(rows, reference):
    actual = {}
    categories = {}
    for row in rows:
        pid, cid = row['patient_id'], row['criterion_id']
        if pid not in CASE_IDS:
            continue
        key = pid, cid
        if key in actual or (pid in categories and categories[pid] != row['patient_category']):
            raise ValueError(f'duplicate or inconsistent result: {key}')
        actual[key] = row['status']
        categories[pid] = row['patient_category']
    if set(actual) != {(p,c) for p in CASE_IDS for c in CRITERIA}:
        raise ValueError('log must contain all 88 criterion results for SAD01-SAD08')
    mismatches = [{'patient_id': p, 'criterion_id': c, 'expected': reference[p,c], 'actual': actual[p,c]}
                  for p,c in sorted(actual) if reference[p,c] != actual[p,c]]
    patients = [{'patient_id': p, 'expected': DECISIONS[reference[p,'DECISION']], 'actual': categories[p]}
                for p in sorted(CASE_IDS) if DECISIONS[reference[p,'DECISION']] != categories[p]]
    computable = [(p,c) for p,c in actual if c != 'I5']
    binary = [(p,c) for p,c in computable if reference[p,c] != 'unknown']
    agreement = lambda keys: round(100*sum(actual[k] == reference[k] for k in keys)/len(keys), 2)
    return {'scope': 'user-designated SAD01-SAD08 ground truth; provenance not independently certified',
            'required_complete_cases': 8, 'complete_cases': len(categories), 'reference_rows': len(reference),
            'computable_criteria': len(computable), 'exact_status_agreement': agreement(computable),
            'binary_reference_criteria': len(binary), 'binary_reference_agreement': agreement(binary),
            'reference_unknowns': len(computable)-len(binary), 'manual_I5_rows': 8,
            'patient_category_agreement': round(100*(8-len(patients))/8,2),
            'criterion_mismatches': mismatches, 'patient_mismatches': patients,
            'all_reference_results_match': not mismatches and not patients}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, default=DEFAULT_LABELS)
    parser.add_argument('--log', type=Path, required=True)
    args = parser.parse_args()
    with args.log.open(encoding='utf-8-sig',newline='') as f:
        result = score(list(csv.DictReader(f)), load_reference(args.labels))
    print(json.dumps(result, indent=2))
    return 0 if result['all_reference_results_match'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
