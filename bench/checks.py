"""Checks on what the LLM said in a benchmark case: rules a script can decide, and yes/no questions a fixed judge model answers."""

import json
import re
import unicodedata
from typing import Any

from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import LLMService

# Formatting a voice never speaks: markdown marks, list items and numbered lines.
MARKUP = re.compile(r"[*#`_\[\]]|^\s*([-•]|\d+\.)\s", re.MULTILINE)

# Words that give away the game-state messages the participant never sees.
LEAK = re.compile(r"game[ -]?state|snapshot|json|\bclient\b|spielzustand|spielstand", re.IGNORECASE)

SENTENCE_END = re.compile(r"[.!?]+(\s|$)")

JUDGE_SYSTEM = """You grade the replies of Iva, a spoken AI lab supervisor in a virtual chemistry lab, in a benchmark.
You get the conversation so far and one yes/no question. Lines in square brackets are what the system did, which the participant never sees: game-state updates and tool calls. The reply the question is about is marked REPLY when there is one.
Answer from the conversation alone. Set pass to true when the answer to the question is yes, and give a one-sentence reason."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass", "reason"],
    "additionalProperties": False,
}


def automatic(text: str) -> dict[str, bool]:
    """Apply the rules every spoken reply has to keep: no formatting or emoji, and nothing that reveals the game-state messages."""
    emoji = any(unicodedata.category(char) == "So" for char in text)
    return {"no_markup": not (MARKUP.search(text) or emoji), "no_leak": not LEAK.search(text)}


def measure(text: str) -> dict[str, int]:
    """Count the words and sentences of a reply, the two numbers that show whether the agent talks too much."""
    return {"words": len(text.split()), "sentences": len(SENTENCE_END.findall(text.strip()))}


def mentions(text: str, wanted: list[str | list[str]]) -> bool:
    """Whether the text names every wanted item, ignoring case, where an item given as a list is satisfied by any one of its alternatives."""
    lowered = text.lower()
    return all(
        any(option.lower() in lowered for option in ([item] if isinstance(item, str) else item)) for item in wanted
    )


def render(transcript: list[tuple[str, str]], marked: int | None) -> str:
    """Write a transcript as the judge reads it, with the entry at the marked index labelled as the reply in question."""
    lines = []
    for index, (who, what) in enumerate(transcript):
        if who == "agent":
            lines.append(f"{'REPLY' if index == marked else 'Iva'}: {what}")
        elif who == "participant":
            lines.append(f"Participant: {what}")
        elif who == "game":
            lines.append(f"[game-state update: {what}]")
        else:
            lines.append(f"[Iva called the tool {what}]")
    return "\n".join(lines)


async def ask(judge: LLMService, transcript: list[tuple[str, str]], marked: int | None, question: str) -> dict[str, Any]:
    """Put one yes/no question about the conversation to the judge model and return its verdict and reason."""
    context = LLMContext(messages=[{"role": "user", "content": f"{render(transcript, marked)}\n\nQuestion: {question}"}])
    answer = await judge.run_inference(context, system_instruction=JUDGE_SYSTEM, response_schema=JUDGE_SCHEMA)
    # A reasoning model answers with a list of thinking and text parts, of which only the text is the verdict.
    if isinstance(answer, list):
        answer = "".join(part.get("text", "") for part in answer if part.get("type") == "text")
    try:
        verdict = json.loads(answer or "")
        return {"pass": bool(verdict["pass"]), "reason": str(verdict["reason"])}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {"pass": None, "reason": f"unreadable verdict: {answer!r}"}


async def evaluate(
    expectations: list[dict[str, Any]],
    text: str,
    tools: list[str],
    judge: LLMService,
    transcript: list[tuple[str, str]],
    marked: int | None,
) -> tuple[dict[str, bool | None], dict[str, str]]:
    """Decide each expectation of a step or a whole case against what the agent said and called, returning pass or fail by id and the judge's reasons."""
    passed: dict[str, bool | None] = {}
    reasons: dict[str, str] = {}
    for expectation in expectations:
        name = expectation["id"]
        if "called" in expectation:
            passed[name] = expectation["called"] in tools
        elif "not_called" in expectation:
            passed[name] = expectation["not_called"] not in tools
        elif "mentions" in expectation:
            passed[name] = mentions(text, expectation["mentions"])
        elif "judge" in expectation:
            verdict = await ask(judge, transcript, marked, expectation["judge"])
            passed[name] = verdict["pass"]
            reasons[name] = verdict["reason"]
        else:
            raise ValueError(f"Expectation '{name}' names no check")
    return passed, reasons
