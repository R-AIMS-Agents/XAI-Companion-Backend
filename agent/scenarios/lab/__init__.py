"""The lab tutor: Iva guides the participant through a chemistry protocol the Unity client runs, reacting to its game events."""

from typing import Any

from loguru import logger

from agent.game import Reaction
from agent.scenarios.lab.prompt import system_prompt

# The reaction to every event the client sends. The session's first snapshot opens the conversation whatever this says.
REACTIONS = {
    "state": Reaction.SILENT,
    "recipe_loaded": Reaction.WHEN_IDLE,
    "flask_placed": Reaction.WHEN_IDLE,
    "wrong_flask": Reaction.WHEN_IDLE,
    "ingredient_fetched": Reaction.WHEN_IDLE,
    "wrong_ingredient": Reaction.WHEN_IDLE,
    "ingredient_poured": Reaction.WHEN_IDLE,
    "combined": Reaction.WHEN_IDLE,
    "wrong_mixture": Reaction.WHEN_IDLE,
    "flask_emptied": Reaction.WHEN_IDLE,
    "placed_on_station": Reaction.SILENT,
    "wrong_station": Reaction.WHEN_IDLE,
    "finished": Reaction.WHEN_IDLE,
    "stored": Reaction.SILENT,
    "game_complete": Reaction.INTERRUPT,
}


def reaction(snapshot: dict[str, Any]) -> Reaction:
    """Look up what an event makes the tutor do; the first recipe's load is silent, since the opening already introduced it."""
    event = snapshot.get("event")
    if event == "recipe_loaded" and (snapshot.get("recipe") or {}).get("index") == 0:
        return Reaction.SILENT
    if event not in REACTIONS:
        logger.warning(f"Unknown game event '{event}', reacting when idle")
        return Reaction.WHEN_IDLE
    return REACTIONS[event]
