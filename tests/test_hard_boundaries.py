"""Adversarial cases from the review; expectations follow protocol/demo policy, not model labels."""
import copy
import pytest
from src.engine import sad_adapter as sa
from src.agent import agent as ag


def observation(case, code):
    return next(e['resource'] for e in case.bundle['entry'] if any(
        c.get('code') == code for c in e['resource'].get('code', {}).get('coding', [])))


def verdict(case, cid):
    return next(v for v in sa.evaluate_case(case, sa.load_spec())[0] if v.criterion_id == cid)


@pytest.mark.parametrize('hours', [0.5, 5.99, True, 'six', None, float('nan'), float('inf')])
def test_invalid_fasting_cannot_pass_or_crash(hours):
    case = sa.load_cases()[0]
    for e in case.bundle['entry']:
        if e['resource']['resourceType'] == 'Specimen':
            e['resource']['collection']['fastingStatusDuration']['value'] = hours
    assert verdict(case, 'I2').status == 'unknown'
    assert verdict(case, 'I4').status == 'unknown'


def test_six_hours_is_inclusive_and_inputs_unchanged():
    case = sa.load_cases()[0]
    for e in case.bundle['entry']:
        if e['resource']['resourceType'] == 'Specimen':
            e['resource']['collection']['fastingStatusDuration']['value'] = 6
    before = copy.deepcopy(case.bundle)
    assert verdict(case, 'I2').status == verdict(case, 'I4').status == 'met'
    assert case.bundle == before


@pytest.mark.parametrize('method', [None, {}, {'text':''}, {'text':'unknown'}, {'text':'Synthetic calculated LDL laboratory result'}])
def test_ldl_requires_supported_method(method):
    case = sa.load_cases()[0]
    observation(case, '18262-6')['method'] = method
    assert verdict(case, 'I2').status == 'unknown'
    assert verdict(case, 'I4').status == 'met'  # no unapproved blanket method requirement


def test_wrong_analyte_is_rejected_at_tool_and_adapter():
    case = sa.load_cases()[0]
    sa.install_store([case])
    spec = sa.load_spec()
    pred = next(p for p in sa.predicates(spec) if p['criterion_id'] == 'I2')
    rc = ag.RecoveryCase(case.case_id, pred, case.screening_date, query_patient_id=case.patient_id)
    tools = {t.tool_spec['name']:t for t in ag.build_tools(rc)}
    assert tools['fhir_query_codes'](codes=['2571-8'])['status'] == 'malformed'
    assert not rc.retrieved
    tg = observation(case, '2571-8')
    # Bypassing the tool and forging the supplied code cannot bypass raw-record validation.
    v = sa.evaluate_with_records(case, spec, 'I2', [{'resource_id':tg['id'], 'code':'2089-1'}])
    assert v.status == 'unknown' and 'rejected' in v.note


@pytest.mark.parametrize('code,method,expected', [
    ('2089-1','Synthetic direct LDL laboratory result','met'),
    ('13457-7','Synthetic calculated LDL laboratory result','met'),
    ('13457-7','Synthetic direct LDL laboratory result','unknown'),
])
def test_recovery_checks_original_method(code, method, expected):
    case = sa.load_cases()[0]
    ldl = observation(case, '18262-6')
    ldl['code']['coding'][0]['code'] = code
    ldl['method'] = {'text':method}
    v = sa.evaluate_with_records(case, sa.load_spec(), 'I2', [{'resource_id':ldl['id']}])
    assert v.status == expected


def test_wrong_system_cannot_be_recovered():
    case = sa.load_cases()[0]
    ldl = observation(case, '18262-6')
    ldl['code']['coding'][0]['system'] = 'https://untrusted.example/codes'
    assert sa.evaluate_with_records(case, sa.load_spec(), 'I2', [{'resource_id':ldl['id']}]).status == 'unknown'


@pytest.mark.parametrize('duration', [None, 'six hours', [], {'value':6,'code':'min'}])
def test_malformed_fasting_object_abstains(duration):
    case = sa.load_cases()[0]
    for e in case.bundle['entry']:
        if e['resource']['resourceType'] == 'Specimen':
            e['resource']['collection']['fastingStatusDuration'] = duration
    assert verdict(case, 'I2').status == 'unknown'


def test_recovery_rejects_foreign_patient():
    case = sa.load_cases()[0]
    ldl = observation(case, '18262-6')
    ldl['subject']['reference'] = 'urn:uuid:someone-else'
    assert sa.evaluate_with_records(case, sa.load_spec(), 'I2', [{'resource_id':ldl['id']}]).status == 'unknown'


def test_equivalence_group_must_match_system_and_not_expand_transitively(monkeypatch):
    loinc = 'http://loinc.org'
    def group(system, *codes):
        return {'codes':[{'system':system,'code':c} for c in codes]}
    monkeypatch.setattr(ag, 'load_equivalents', lambda: ([group(loinc,'A','B'), group(loinc,'B','C'),
                                                       group('other','A','D')], 'test'))
    assert ag.allowed_equivalents({'codes':[{'system':loinc,'code':'A'}]}) == {(loinc,'A'),(loinc,'B')}


def test_conflict_resolution_cannot_bypass_method_guard(monkeypatch):
    from src.agent import conflict, llm
    from src import config
    case = next(c for c in sa.load_cases() if c.case_id == 'SAD07')
    for e in case.bundle['entry']:
        if any(c.get('code') == '18262-6' for c in e['resource'].get('code', {}).get('coding', [])):
            e['resource'].pop('method', None)
    v = verdict(case, 'I2')
    monkeypatch.setattr(config, 'IMMATERIAL_CONFLICT_RESOLVES', True)
    monkeypatch.setattr(llm, 'structured_call', lambda *a, **kw: conflict.ConflictNote(differences='x', likely_cause='x', what_to_check='x'))
    out = conflict.explain(case, sa.load_spec(), v, sa.load_engine())
    assert out.status == 'unknown' and out.conflict
