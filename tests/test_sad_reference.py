import csv

import pytest

from eval.sad_reference import CASE_IDS, CRITERIA, DECISIONS, load_reference, score


def reference_rows():
    reference = load_reference()
    return reference, [
        {'patient_id': p, 'criterion_id': c, 'status': reference[p, c],
         'patient_category': DECISIONS[reference[p, 'DECISION']]}
        for p in sorted(CASE_IDS) for c in sorted(CRITERIA)
    ]


def test_complete_eight_case_reference_preserves_unknown_and_review():
    reference, rows = reference_rows()
    result = score(rows, reference)
    assert len(reference) == 96
    assert result['computable_criteria'] == 80
    assert result['binary_reference_criteria'] == 78
    assert result['all_reference_results_match']
    assert result['patient_category_agreement'] == 100
    assert reference['SAD07', 'I2'] == 'unknown'
    assert reference['SAD07', 'DECISION'] == 'review'


def test_unknown_reference_cannot_be_replaced_by_met():
    reference, rows = reference_rows()
    next(r for r in rows if (r['patient_id'], r['criterion_id']) == ('SAD07', 'I2'))['status'] = 'met'
    result = score(rows, reference)
    assert not result['all_reference_results_match']
    assert result['exact_status_agreement'] == 98.75
    assert result['binary_reference_agreement'] == 100


def test_missing_or_duplicate_result_rejected():
    reference, rows = reference_rows()
    with pytest.raises(ValueError):
        score(rows[:-1], reference)
    with pytest.raises(ValueError):
        score(rows + rows[:1], reference)


def test_extended_cases_do_not_change_required_cohort():
    reference, rows = reference_rows()
    rows.append({'patient_id': 'EXT01', 'criterion_id': 'I2'})
    assert score(rows, reference)['complete_cases'] == 8


def test_duplicate_reference_rejected(tmp_path):
    path = tmp_path / 'duplicate.csv'
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['case_id', 'criterion_id', 'ai_draft_expected'])
        writer.writerows([['SAD01', 'I1', 'met']] * 2)
    with pytest.raises(ValueError, match='duplicate'):
        load_reference(path)
