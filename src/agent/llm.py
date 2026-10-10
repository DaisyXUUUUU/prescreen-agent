"""One place for single-shot structured model calls (free-text interpretation, conflict notes).

Tests replace `structured_call` so nothing reaches Bedrock offline.
"""

from pydantic import BaseModel


def structured_call(system_prompt: str, prompt: str, schema: type[BaseModel], model=None) -> BaseModel:
    from strands import Agent

    from src.agent.agent import make_model, retry_strategy

    agent = Agent(model=model or make_model(), system_prompt=system_prompt, structured_output_model=schema,
                  callback_handler=None, retry_strategy=retry_strategy())
    return agent(prompt).structured_output


def norm(text: str) -> str:
    return " ".join((text or "").lower().replace("’", "'").split())


def quote_found(quote: str, source: str) -> bool:
    """A quote counts only if it really occurs in the source text (whitespace/case-insensitive)."""
    q = norm(quote).strip(" .\"'")
    return len(q) >= 4 and q in norm(source)
