import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from src.tools import local_io


def test_atomic_utf8_lf_and_concurrent_writers(tmp_path):
    path = tmp_path / 'shared.json'
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda i: local_io.atomic_write(path, json.dumps({'i':i,'text':'审查'})+'\r\n'), range(30)))
    assert json.loads(local_io.read_utf8(path))['i'] in range(30)
    assert b'\r' not in path.read_bytes()
    assert not list(tmp_path.glob('*.tmp'))


def test_sharing_violation_retries_then_succeeds(tmp_path, monkeypatch):
    real = local_io.os.replace
    calls = []
    def replace(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError('sharing violation')
        real(src, dst)
    monkeypatch.setattr(local_io.os, 'replace', replace)
    monkeypatch.setattr(local_io.time, 'sleep', lambda _:None)
    local_io.atomic_write(tmp_path/'x', 'é\r\n')
    assert (tmp_path/'x').read_bytes() == 'é\n'.encode()
    assert len(calls) == 3


def test_permanent_failure_is_bounded_and_cleans_temp(tmp_path, monkeypatch):
    def fail(*args):
        raise PermissionError('permanent')
    monkeypatch.setattr(local_io.os, 'replace', fail)
    monkeypatch.setattr(local_io.time, 'sleep', lambda _:None)
    with pytest.raises(PermissionError):
        local_io.atomic_write(tmp_path/'x', 'x')
    assert not list(tmp_path.iterdir())
