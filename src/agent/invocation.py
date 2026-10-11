"""Bound every SDK invocation, including structured-output repair loops."""
import asyncio
import threading


def invoke(agent, prompt, *, turns=8, timeout_s=120):
    cancel = threading.Event()
    timer = threading.Timer(timeout_s, cancel.set)
    timer.daemon = True
    timer.start()
    try:
        result = agent(prompt, limits={'turns':turns}, cancel_signal=cancel)
        if cancel.is_set():
            raise TimeoutError(f'agent invocation exceeded {timeout_s}s')
        reason = getattr(result, 'stop_reason', '') or ''
        if reason.startswith(('limit_', 'cancel')):
            raise RuntimeError(f'agent invocation stopped: {reason}')
        return result
    except asyncio.CancelledError as exc:
        if cancel.is_set():
            raise TimeoutError(f'agent invocation exceeded {timeout_s}s') from exc
        raise
    finally:
        timer.cancel()
