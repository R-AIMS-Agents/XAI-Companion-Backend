"""What the agent is told it is. Placeholder until the study's interaction and explanation behaviour are designed."""

# The languages a session can be held in, by the code the services take, with the name the prompt uses for each.
LANGUAGES = {"en": "English", "de": "German"}

_PERSONA = "You are a helpful virtual human. Answer briefly and conversationally, in plain spoken language."

# Spoken verbatim on connect, before the LLM sees any turn, so every participant hears the same opening.
GREETING = {"en": "Hello and welcome.", "de": "Hallo und willkommen."}


def system_prompt(language: str) -> str:
    """Return the system prompt with the session's language pinned, so the agent does not drift into another one mid-session."""
    return f"{_PERSONA} Respond in {LANGUAGES[language]}."
