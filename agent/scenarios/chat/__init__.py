"""Open conversation with no task. Placeholder until a study gives the agent something to be about."""

from agent.config import LANGUAGES

_PERSONA = "You are a helpful virtual human. Answer briefly and conversationally, in plain spoken language."

# Spoken verbatim on connect, before the LLM sees any turn, so every participant hears the same opening.
GREETING = {"en": "Hello and welcome.", "de": "Hallo und willkommen."}


def system_prompt(language: str) -> str:
    """Return the system prompt with the session's language pinned, so the agent does not drift into another one mid-session."""
    return f"{_PERSONA} Respond in {LANGUAGES[language]}."
