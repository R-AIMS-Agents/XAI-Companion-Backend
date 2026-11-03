"""The lab tutor: Iva introduces herself as an AI, then guides the participant through a chemistry protocol the Unity client runs, reacting to its game events."""

from typing import Any

from loguru import logger

from agent.game import Reaction
from agent.scenarios.lab.prompt import system_prompt

# Spoken verbatim once the client is ready, so every participant hears the same disclosure that Iva is an AI agent that can make mistakes.
GREETING = {
    "en": "Hi, great to have you here! I'm Iva, an AI agent, and what I hear, say and answer is handled by several models. I can make mistakes, so if something I say seems off, just ask again. I'll be supervising you in the lab today. What should I call you?",
    "de": "Hallo, schön, dass du da bist! Ich bin Iva, eine KI-Agentin, und was ich höre, sage und antworte, übernehmen mehrere Modelle. Ich kann mich irren, also frag ruhig nach, wenn dir etwas komisch vorkommt. Ich betreue dich heute hier im Labor. Wie darf ich dich nennen?",
}

# The reaction to every event the client sends, once the intro is over.
REACTIONS = {
    "state": Reaction.SILENT,
    "recipe_loaded": Reaction.SILENT,
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
    "stored": Reaction.WHEN_IDLE,
    "game_complete": Reaction.INTERRUPT,
}


def reaction(snapshot: dict[str, Any]) -> Reaction:
    """Look up what an event makes the tutor do, reacting when idle to an event the table does not know."""
    event = snapshot.get("event")
    if event not in REACTIONS:
        logger.warning(f"Unknown game event '{event}', reacting when idle")
        return Reaction.WHEN_IDLE
    return REACTIONS[event]
