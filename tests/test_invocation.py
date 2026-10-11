import asyncio
from types import SimpleNamespace
import pytest
from src.agent.invocation import invoke


def test_turn_budget_is_enforced():
    def agent(prompt, *, limits, cancel_signal):
        assert limits == {'turns': 3}
        return SimpleNamespace(stop_reason='limit_turns')
    with pytest.raises(RuntimeError, match='limit_turns'):
        invoke(agent, 'test', turns=3)


def test_own_timeout_becomes_catchable_error():
    def agent(prompt, *, limits, cancel_signal):
        assert cancel_signal.wait(1)
        raise asyncio.CancelledError()
    with pytest.raises(TimeoutError):
        invoke(agent, 'test', timeout_s=0.01)


def test_external_cancellation_is_preserved():
    def agent(*args, **kwargs):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        invoke(agent, 'test')


@pytest.mark.parametrize('response,valid', [('{"ok":true}',True), ('```json\n{"ok":true}\n```',True),
                                          ('{"ok":null}',False), ('not JSON',False)])
def test_structured_facts_have_bounded_format_repair(monkeypatch, response, valid):
    import strands
    from pydantic import BaseModel, ValidationError
    from src.agent.llm import structured_call
    class Facts(BaseModel):
        ok: bool
    calls = []
    def factory(**kwargs):
        assert 'structured_output_model' not in kwargs
        def invoke_once(*args, **kw):
            calls.append(1)
            return response
        return invoke_once
    monkeypatch.setattr(strands, 'Agent', factory)
    if valid:
        assert structured_call('extract', 'test', Facts, model=object()).ok is True
    else:
        with pytest.raises(ValidationError):
            structured_call('extract', 'test', Facts, model=object())
    assert len(calls) == (1 if valid else 2)


def test_structured_format_repair_can_succeed(monkeypatch):
    import strands
    from pydantic import BaseModel
    from src.agent.llm import structured_call
    class Facts(BaseModel):
        ok: bool
    responses = iter(['{"wrong_key":true}', '{"ok":true}'])
    monkeypatch.setattr(strands, 'Agent', lambda **kw: lambda *a, **k: next(responses))
    assert structured_call('extract', 'test', Facts, model=object()).ok is True
