"""The scenarios a session can run: what the agent is told it is, how it opens, and which game events it reacts to. The single place they are listed."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.game import Reaction
from agent.scenarios import chat, lab


@dataclass(frozen=True)
class Scenario:
    """What one session is about, everything a scenario varies and nothing the model stack does."""

    system_prompt: Callable[[str], str]
    # Spoken verbatim once the client is ready, or None for a scenario whose opening is the LLM's first run. With a game, it opens an intro that holds every game reaction until the agent starts the task.
    greeting: dict[str, str] | None = None
    # How the agent reacts to each game snapshot, or None for a scenario without a game.
    reaction: Callable[[dict[str, Any]], Reaction] | None = None


SCENARIOS = {
    "chat": Scenario(system_prompt=chat.system_prompt, greeting=chat.GREETING),
    "lab": Scenario(system_prompt=lab.system_prompt, greeting=lab.GREETING, reaction=lab.reaction),
}

DEFAULT = "chat"
