"""One place for single-shot structured model calls (free-text interpretation, conflict notes).

Tests replace `structured_call` so nothing reaches Bedrock offline.
"""

import json
import re
import time
from pydantic import BaseModel, ValidationError
from src.agent.invocation import invoke


def structured_call(system_prompt: str, prompt: str, schema: type[BaseModel], model=None) -> BaseModel:
    from strands import Agent

    from src.agent.agent import make_model, retry_strategy

    # Nova does not support strict tool schemas. Validate JSON locally and permit
    # only one format repair, within a shared deadline, instead of an unbounded SDK loop.
    output_contract = '\nReturn only one JSON object matching this schema. Do not add prose.\n' + json.dumps(schema.model_json_schema())
    agent = Agent(model=model or make_model(), system_prompt=system_prompt + output_contract,
                  callback_handler=None, retry_strategy=retry_strategy())
    deadline = time.monotonic() + 60
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('structured facts exceeded 60s deadline')
        result = invoke(agent, prompt, turns=3, timeout_s=remaining)
        raw = str(result).strip()
        fenced = re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
        try:
            return schema.model_validate_json(fenced.group(1) if fenced else raw)
        except ValidationError as exc:
            if attempt:
                raise
            errors = [{'field': e['loc'], 'error': e['msg']} for e in exc.errors()]
            prompt = ('Your JSON failed validation: ' + json.dumps(errors) +
                      '. Return one complete corrected JSON object matching the schema. '
                      'Correct field names and types only; do not invent missing facts. This is the final format attempt.')


def norm(text: str) -> str:
    return " ".join((text or "").lower().replace("’", "'").split())


def quote_found(quote: str, source: str) -> bool:
    """A quote counts only if it really occurs in the source text (whitespace/case-insensitive)."""
    q = norm(quote).strip(" .\"'")
    return len(q) >= 4 and q in norm(source)
