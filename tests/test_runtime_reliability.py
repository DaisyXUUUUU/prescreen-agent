"""Fail closed on incomplete evaluation, mismatched dates and mixed amendment modes."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.amendment import monitor
from src.engine import sad_adapter as sa
from src.agent import agent as ag
from src import config

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize('rows', [
    'P,I2,\n', 'P,I2,unknown\n', 'P,PATIENT,undetermined\n', 'P,I2,met\nP,I2,not_met\n'])
def test_unreviewed_or_duplicate_labels_rejected(tmp_path, rows):
    ev = load('eval/evaluate.py', 'eval_labels')
    path = tmp_path/'labels.csv'
    path.write_text('patient_id,criterion_id,expected\n'+rows, encoding='utf-8-sig')
    with pytest.raises(ValueError, match='review before evaluation'):
        ev.load_labels(path)


@pytest.mark.parametrize('accuracy,expected', [(81.1,False),(90,True),(None,False)])
def test_measured_targets_are_acceptance_gates(accuracy, expected):
    ev = load('eval/evaluate.py','eval_targets')
    metrics = {'failures':{name:True for name in ev.RUNS if name != 'baseline'},
               'patient':{'wrongful_exclusions':[],'sensitivity':100},
               'criterion':{'accuracy_strict':accuracy}, 'evidence':{'coverage':100},
               'trace':{'coverage':100},'amendment':{'recall':100}}
    assert (not ev.acceptance_failures(metrics)) is expected


def test_no_agent_amendment_never_constructs_model(monkeypatch):
    def fail():
        pytest.fail('model constructed with --no-agent')
    monkeypatch.setattr(monitor, 'make_model', fail)
    r = monitor.check('LDL >=70\nStable treatment', 'LDL >=100\nAdequate treatment', 'a', 'b', use_agent=False)
    assert {c.label for c in r.changes} <= {'substantive','ambiguous'}
    c = monitor.classify(monitor.Change('modified','X','stable treatment','adequate treatment'), use_agent=False)
    assert c.label == 'ambiguous' and c.trace[-1]['tool'] == 'rule:model_disabled'


def test_reuse_missing_never_launches_or_accepts_stale_outputs(tmp_path, monkeypatch):
    ev = load('eval/evaluate.py','eval_reliability')
    monkeypatch.setattr(ev.subprocess, 'run', lambda *a, **kw: pytest.fail('reuse must not execute'))
    args = SimpleNamespace(trial='SAD',date='2026-10-09',reuse=True,no_agent=True,jobs=1)
    assert ev.run_all(args,tmp_path) == {}
    assert set(args.execution_failures) == set(ev.RUNS)
    assert json.loads((tmp_path/'execution_status.json').read_text())['complete'] is False


def test_child_failure_ignores_previous_completion_marker(tmp_path, monkeypatch):
    ev = load('eval/evaluate.py','eval_child_failure')
    monkeypatch.setattr(ev, 'RUNS', ['baseline'])
    out = tmp_path/'baseline'
    out.mkdir()
    marker = out/'run_SAD_2026-10-09.json'
    marker.write_text('{}')
    monkeypatch.setattr(ev.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1))
    args = SimpleNamespace(trial='SAD',date='2026-10-09',reuse=False,no_agent=True,jobs=1,
                           nct=None,predicates=None,patients=None)
    assert ev.run_all(args,tmp_path) == {}
    assert not marker.exists() and 'exit 1' in args.execution_failures['baseline']


def test_evaluation_invalidates_previous_success_before_start(tmp_path, monkeypatch):
    ev = load('eval/evaluate.py', 'eval_in_progress')
    monkeypatch.setattr(ev, 'RUNS', ['baseline'])
    status = tmp_path/'execution_status.json'
    status.write_text('{"complete":true}')
    def child(*args, **kwargs):
        assert json.loads(status.read_text())['complete'] is False
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(ev.subprocess, 'run', child)
    args = SimpleNamespace(trial='SAD', date='2026-10-09', reuse=False, no_agent=True,
                           jobs=1, nct=None, predicates=None, patients=None)
    assert ev.run_all(args,tmp_path) == {}


def test_sad_date_mismatch_fails_before_network(monkeypatch):
    cli = load('run.py','cli_date')
    monkeypatch.setattr(cli.sys,'argv',['run.py','--trial','SAD','--date','2026-10-12','--no-agent'])
    monkeypatch.setattr(cli,'ctgov_fetch',lambda _:pytest.fail('network before date validation'))
    assert cli.main() == 2


def test_preflight_is_not_repeated_for_prepared_screen(monkeypatch):
    monkeypatch.setattr(ag,'preflight',lambda:pytest.fail('second preflight'))
    cases=sa.load_cases()
    results,*_=sa.screen(cases,sa.load_spec(),use_agent=False,preflight_done=True)
    assert len(results) == 8


def test_cli_pins_fallback_for_both_versions(tmp_path, monkeypatch):
    from src.tools.ctgov import FetchResult
    cli = load('run.py','cli_modes')
    fix=ROOT/'tests/fixtures/sad'
    monkeypatch.setattr(config,'FAILURES',{k:False for k in config.FAILURES})
    monkeypatch.setattr(config,'S3_BUCKET','')
    monkeypatch.setattr(cli.sys,'argv',['run.py','--trial','SAD','--date','2026-10-09','--no-extended-cases',
        '--out',str(tmp_path),'--fail','amendment_v2','--v1-snapshot',str(fix/'NCT07347678_v1.txt'),
        '--v2-snapshot',str(fix/'NCT07347678_v2.txt'),'--v2-predicates',str(fix/'sad-1.0.1-sample.json')])
    count=[]
    monkeypatch.setattr(ag,'preflight',lambda:(count.append(1) or None,'throttled'))
    monkeypatch.setattr(cli,'ctgov_fetch',lambda _:FetchResult('ok','NCT07347678',criteria={},fetched_at='2026-10-11',sha256='x'))
    assert cli.main() == 0
    assert len(count) == 1
    meta=json.loads((tmp_path/'run_SAD_2026-10-09.json').read_text())
    impact=json.loads((tmp_path/'amendment_impact_SAD_2026-10-09.json').read_text())
    assert meta['execution_mode'] == impact['execution_mode'] == 'rules_only'


def test_unchanged_criteria_reuse_interpretation_without_model(monkeypatch):
    from src.amendment.rescreen import unchanged_verdicts
    from src.agent import interpret
    case=sa.load_cases(config.DATA_DIR/'extended_cases/cases')[0]
    spec=sa.load_spec()
    results,*_=sa.screen([case],spec,use_agent=False)
    old=next(v for v in results[0].verdicts if v.criterion_id=='E3')
    old.status='unknown'
    old.note='frozen v1 range interpretation'
    reuse=unchanged_verdicts(results,sa.predicates(spec),sa.predicates(spec))
    monkeypatch.setattr(interpret,'interpret',lambda *a,**kw:pytest.fail('unaffected interpretation repeated'))
    updated,*_=sa.screen([case],spec,use_agent=True,preflight_done=True,reused_verdicts=reuse)
    new=next(v for v in updated[0].verdicts if v.criterion_id=='E3')
    assert new.note == old.note and new is not old
    assert new.trace[-1]['tool']=='rule:amendment_reuse'
