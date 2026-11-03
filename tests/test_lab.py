"""The lab tutor: a reaction for every event the client sends, and a prompt that names the equipment as the participant will hear it."""

import pytest

from agent.config import LANGUAGES
from agent.game import Reaction
from agent.scenarios import SCENARIOS, lab

# Every event the Unity client sends, as its contract lists them.
EVENTS = {
    "state",
    "recipe_loaded",
    "flask_placed",
    "wrong_flask",
    "ingredient_fetched",
    "wrong_ingredient",
    "ingredient_poured",
    "combined",
    "wrong_mixture",
    "flask_emptied",
    "placed_on_station",
    "wrong_station",
    "finished",
    "stored",
    "game_complete",
}


def test_every_event_the_client_sends_has_a_reaction():
    """An event missing from the table would fall back to speaking, so the table and the contract are held to the same list."""
    assert lab.REACTIONS.keys() == EVENTS


def test_storing_a_compound_announces_the_next_and_loading_one_is_silent():
    """Unity sends recipe_loaded only for the first compound, before the agent connects, so the next compound is announced on stored."""
    assert lab.reaction({"event": "recipe_loaded", "recipe": {"index": 0}}) is Reaction.SILENT
    assert lab.reaction({"event": "stored", "recipe": {"index": 1}}) is Reaction.WHEN_IDLE


def test_finishing_the_protocol_interrupts():
    """The end of the game matters more than whatever the tutor was saying."""
    assert lab.reaction({"event": "game_complete"}) is Reaction.INTERRUPT


def test_an_unknown_event_is_reacted_to_rather_than_ignored():
    """A new event from the client still reaches the participant, if more talkatively than intended."""
    assert lab.reaction({"event": "something_new"}) is Reaction.WHEN_IDLE


@pytest.mark.parametrize("language, names", [("en", ["round-bottom flask", "ice bath"]), ("de", ["Rundkolben", "Eisbad", "du"])])
def test_the_prompt_names_the_equipment_in_the_session_language(language, names):
    """The tutor names equipment as the participant hears it, and holds the session's language."""
    prompt = lab.system_prompt(language)

    assert f"Speak {LANGUAGES[language]}." in prompt
    for name in names:
        assert name in prompt


@pytest.mark.parametrize(
    "language, disclosure",
    [("en", ["an AI agent", "several models", "I can make mistakes"]), ("de", ["KI-Agentin", "mehrere Modelle", "Ich kann mich irren"])],
)
def test_the_lab_opens_with_a_greeting_that_discloses_an_ai(language, disclosure):
    """Every participant hears the same words saying Iva is an AI agent built from several models that can make mistakes, before the intro the game waits for."""
    for words in disclosure:
        assert words in SCENARIOS["lab"].greeting[language]
    assert SCENARIOS["lab"].reaction is lab.reaction


def test_the_prompt_tells_the_tutor_when_to_start_the_task():
    """The intro ends only when the tutor calls the tool, so the prompt has to name it."""
    assert "start_task" in lab.system_prompt("en")
