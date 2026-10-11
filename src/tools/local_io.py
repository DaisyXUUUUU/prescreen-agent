"""UTF-8/LF atomic files, including bounded retries for Windows sharing violations."""
import os
import tempfile
import time
from pathlib import Path


def retry_io(operation):
    for attempt in range(8):
        try:
            return operation()
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.02 * 2 ** attempt, 0.25))


def read_utf8(path):
    return retry_io(lambda: Path(path).read_text(encoding='utf-8'))


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as f:
            name = f.name
            f.write(text.replace('\r\n', '\n').replace('\r', '\n').encode('utf-8'))
            f.flush()
            os.fsync(f.fileno())
        retry_io(lambda: os.replace(name, path))
    finally:
        if name and os.path.exists(name):
            retry_io(lambda: os.unlink(name))
