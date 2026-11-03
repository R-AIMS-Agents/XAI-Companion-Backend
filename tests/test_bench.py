"""The benchmark's offline parts: word error rate, the rule checks, the case files, and measuring a snapshot the catalog does not list."""

from pathlib import Path

import pytest

from agent import scenarios
from agent.config import LANGUAGES, Config
from bench import checks, llm, stt

CONFIG = Config("ws://localhost", "key", "secret", "room", "mistral-key", "elevenlabs-key")

STEP_KINDS = {"game", "say", "agent", "tool"}


def test_a_transcript_differing_only_in_case_and_punctuation_has_no_errors():
    """Formatting is the STT's choice, not a recognition error, so it costs nothing."""
    assert stt.wer("Oh boy this is going to be incredible.", "Oh boy. This is going to be incredible!") == 0.0


def test_hyphenated_compounds_count_as_their_parts():
    """'Mars-Riegel' and 'Mars Riegel' are the same words heard."""
    assert stt.wer("drei Mars-Riegel", "drei Mars Riegel") == 0.0


def test_each_wrong_missing_or_extra_word_counts_once():
    """A substitution, a deletion and an insertion each add one error per reference word."""
    reference = "so three mars bars into the pan"
    assert stt.wer(reference, "so three mars cars into the pan") == pytest.approx(1 / 7, abs=1e-4)
    assert stt.wer(reference, "so three mars into the pan") == pytest.approx(1 / 7, abs=1e-4)
    assert stt.wer(reference, "so three mars bars into the hot pan") == pytest.approx(1 / 7, abs=1e-4)


@pytest.mark.parametrize("text", ["**Great**, Mirko!", "- take the flask", "1. Take the flask", "Well done 🎉"])
def test_formatting_and_emoji_fail_the_spoken_style(text):
    """Nothing a voice cannot speak may reach the TTS."""
    assert checks.automatic(text)["no_markup"] is False


@pytest.mark.parametrize("text", ["The game state says you are done.", "Laut Spielzustand bist du fertig."])
def test_naming_the_game_state_fails_the_leak_check(text):
    """The participant never sees the game-state messages, so the agent must not refer to them."""
    assert checks.automatic(text)["no_leak"] is False


def test_a_plain_spoken_reply_passes_the_automatic_checks():
    """An ordinary reply is not caught by either rule."""
    assert checks.automatic("Great, Mirko! Now take the Erlenmeyer flask from the shelf.") == {"no_markup": True, "no_leak": True}


def test_mentions_takes_any_one_of_listed_alternatives():
    """A list inside the wanted items is satisfied by one of its alternatives, ignoring case."""
    assert checks.mentions("Das ist Flame, die rote Flasche.", ["flame", ["red", "rot"]])
    assert not checks.mentions("Das ist Flame.", ["flame", ["red", "rot"]])


async def test_rule_expectations_are_decided_without_the_judge():
    """Tool and mention checks need no model, so a case of only those runs offline."""
    expectations = [
        {"id": "starts", "called": "start_task"},
        {"id": "no_other", "not_called": "other"},
        {"id": "names", "mentions": ["Erlenmeyer"]},
    ]
    passed, reasons = await checks.evaluate(expectations, "Take the Erlenmeyer flask.", ["start_task"], None, [], None)

    assert passed == {"starts": True, "no_other": True, "names": True}
    assert reasons == {}


def _llm_cases():
    """Every LLM case file by name."""
    return llm.load(None).items()


@pytest.mark.parametrize("name, case", _llm_cases(), ids=[name for name, _ in _llm_cases()])
def test_every_llm_case_is_well_formed(name, case):
    """A case names a scenario and language a session can run, every step is one known kind, and every expectation has an id and one check."""
    assert case["scenario"] in scenarios.SCENARIOS
    assert case["language"] in LANGUAGES
    assert case["about"]
    runs = 0
    for step in case["steps"]:
        assert len(STEP_KINDS & step.keys()) == 1, step
        if "game" in step:
            assert {"event", "detail", "recipe", "complete"} <= step["game"].keys()
        runs += step.get("run", "say" in step)
        for expectation in step.get("expect", []):
            assert expectation["id"] and len(expectation.keys() - {"id"}) == 1
    assert runs, f"{name} never runs the LLM"


def _stt_cases():
    """Every STT case file by name."""
    return stt.load(None).items()


@pytest.mark.parametrize("name, case", _stt_cases(), ids=[name for name, _ in _stt_cases()])
def test_every_stt_case_has_its_recording_and_a_reference(name, case):
    """A case without its audio or reference transcript could not be scored."""
    assert (Path(stt.ROOT) / case["audio"]).is_file()
    assert case["language"] in LANGUAGES
    assert case["reference"].strip()


def test_a_snapshot_the_catalog_does_not_list_can_be_measured():
    """Older models stay measurable after the catalog moves on, by naming their snapshot in place of the entry's own."""
    assert llm.build("mistral-small", CONFIG, model="mistral-medium-2604").settings.model == "mistral-medium-2604"
    assert llm.build("mistral-small", CONFIG, model=None).settings.model == "mistral-small-2603"


def test_a_snapshot_can_be_measured_at_a_reasoning_effort_it_accepts():
    """An older snapshot may refuse the entry's reasoning effort, so the benchmark can name another and keep everything else."""
    service = llm.build("mistral-small", CONFIG, model="mistral-large-2512", reasoning_effort="low")

    assert service.settings.model == "mistral-large-2512"
    assert service.settings.extra == {"reasoning_effort": "low"}
    assert llm.build("mistral-small", CONFIG).settings.extra == {"reasoning_effort": "none"}


def test_an_argument_the_entry_does_not_bind_is_refused():
    """Replacing something the catalog entry never set would silently measure a different setup, so it stops at once."""
    with pytest.raises(SystemExit):
        llm.build("mistral-small", CONFIG, temperature="0.2")


def test_an_entry_not_bound_to_a_model_refuses_a_replacement():
    """Nemotron's model is fixed by its container, so naming another one stops at once."""
    with pytest.raises(SystemExit):
        stt.build("nemotron", "another-model", CONFIG, None)
