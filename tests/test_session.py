"""Session resolution: what the command line settles, what the dialog is asked, and what neither has to."""

import sys
import tkinter as tk

import pytest

import agent.ui
from agent import scenarios, session
from agent.config import LANGUAGES
from agent.services import catalog

# Participant and language always need an answer, and there is more than one scenario, so a headless command line names all three.
HEADLESS = ["--participant", "P04", "--language", "en", "--scenario", "chat"]


def _stub(config, language=None):
    """Stand in for a service factory, which resolution never calls."""
    return None


@pytest.fixture(autouse=True)
def never_open_a_window(monkeypatch):
    """Guard every test: reaching Tk means a real dialog, which would sit waiting for a person who is not there."""

    def refuse(*args, **kwargs):
        raise AssertionError("resolve() opened the dialog")

    monkeypatch.setattr(tk, "Tk", refuse)


@pytest.fixture
def catalogue(monkeypatch):
    """Point the session at a catalog of a known shape, so these tests describe the rule and not the catalog's size."""

    def use(**registries):
        monkeypatch.setattr(
            session,
            "FIELDS",
            {field: dict.fromkeys(names, _stub) for field, names in registries.items()},
        )
        # The last name of each field is the default, so a test fails if resolution silently falls back to the first.
        monkeypatch.setattr(
            catalog, "DEFAULTS", {field: names[-1] for field, names in registries.items()}
        )
        monkeypatch.setattr(catalog, "TTS_LANGUAGES", dict.fromkeys(registries["tts"], set(LANGUAGES)))

    return use


def _expect_no_dialog(monkeypatch):
    """Arrange for an opened dialog to be an import error rather than a window."""
    monkeypatch.delitem(sys.modules, "agent.ui.chooser", raising=False)
    monkeypatch.delattr(agent.ui, "chooser", raising=False)


def _accept(asked=None):
    """Stand in for the dialog: record what it was asked and accept the preselection, as a person hitting Start would."""

    def fake_choose(languages, options, defaults, suggested, problem):
        if asked is not None:
            asked.update(languages=languages, options=options, defaults=defaults, suggested=suggested)
        return {**defaults, "participant": defaults["participant"] or suggested[0]}

    return fake_choose


def test_a_complete_command_line_needs_no_dialog(monkeypatch, catalogue):
    """Naming the participant, the language and every model resolves the session without importing the chooser, which is the headless path."""
    catalogue(stt=["voxtral", "whisper"], llm=["small", "medium"], tts=["flash", "kokoro"])
    monkeypatch.setattr(
        sys, "argv", ["run.py", *HEADLESS, "--stt", "whisper", "--llm", "medium", "--tts", "kokoro"]
    )
    _expect_no_dialog(monkeypatch)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("whisper", "medium", "kokoro")
    assert (run.participant, run.language) == ("P04", "en")
    assert run.transport == "livekit"
    assert "agent.ui.chooser" not in sys.modules


def test_a_sole_implementation_is_settled_without_asking(monkeypatch, catalogue):
    """A model field with one implementation has nothing to decide, so naming participant and language is enough to stay headless."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    monkeypatch.setattr(sys, "argv", ["run.py", *HEADLESS])
    _expect_no_dialog(monkeypatch)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "small", "flash")
    assert "agent.ui.chooser" not in sys.modules


@pytest.mark.parametrize("missing", ["--participant", "--language"])
def test_a_missing_participant_or_language_opens_the_dialog(monkeypatch, catalogue, missing):
    """Even with every model settled, a session cannot start without knowing who it is for and in which language."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    argv = list(HEADLESS)
    del argv[argv.index(missing) : argv.index(missing) + 2]
    monkeypatch.setattr(sys, "argv", ["run.py", *argv])
    asked = {}
    monkeypatch.setattr("agent.ui.chooser.choose", _accept(asked))

    session.resolve()

    assert asked, "the dialog was not opened"


def test_the_dialog_opens_on_the_stated_default(monkeypatch, catalogue):
    """The default is the one named in the catalog, not whichever implementation happens to sort first."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["aaa-sorts-first", "the-default"])
    monkeypatch.setattr(sys, "argv", ["run.py"])
    asked = {}
    monkeypatch.setattr("agent.ui.chooser.choose", _accept(asked))

    run = session.resolve()

    assert asked["defaults"]["tts"] == "the-default"
    assert run.tts == "the-default"


def test_the_real_catalog_defaults_to_the_documented_stack(monkeypatch):
    """The stack a bare run uses is the one the project settled on, whatever else the catalog gains."""
    monkeypatch.setattr(sys, "argv", ["run.py"])
    monkeypatch.setattr("agent.ui.chooser.choose", _accept())

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "mistral-small", "elevenlabs-flash")
    assert run.language == "en"


@pytest.mark.parametrize("field", ["stt", "llm", "tts"])
def test_every_default_is_an_implementation_the_catalog_holds(field):
    """A default naming a model that does not exist would fail only at startup, and only for that field."""
    assert catalog.DEFAULTS[field] in session.FIELDS[field]


def test_the_dialog_shows_the_whole_session(monkeypatch, catalogue):
    """Every field arrives preselected and every field is offered, so the dialog reads as the session about to run."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash", "kokoro"])
    monkeypatch.setattr(sys, "argv", ["run.py"])
    monkeypatch.setattr(session.roster, "suggest", lambda: "P07")
    asked = {}
    monkeypatch.setattr("agent.ui.chooser.choose", _accept(asked))

    run = session.resolve()

    assert asked["defaults"] == {
        "participant": "",
        "language": "en",
        "scenario": scenarios.DEFAULT,
        "stt": "voxtral",
        "llm": "small",
        "tts": "kokoro",
    }
    assert asked["languages"] == LANGUAGES
    assert asked["options"] == {
        "scenario": sorted(scenarios.SCENARIOS),
        "stt": ["voxtral"],
        "llm": ["small"],
        "tts": ["flash", "kokoro"],
    }
    assert asked["suggested"] == ["P07", "test"]
    assert run.participant == "P07"


def test_naming_the_only_real_choice_settles_it(monkeypatch, catalogue):
    """Naming the one model field that has a choice leaves nothing to ask, so the dialog stays shut."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash", "kokoro"])
    monkeypatch.setattr(sys, "argv", ["run.py", *HEADLESS, "--tts", "kokoro"])
    _expect_no_dialog(monkeypatch)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "small", "kokoro")
    assert "agent.ui.chooser" not in sys.modules


@pytest.mark.parametrize(
    "field, registry",
    [("stt", catalog.STT), ("llm", catalog.LLM), ("tts", catalog.TTS)],
)
def test_the_command_line_offers_exactly_what_the_catalog_holds(field, registry, monkeypatch):
    """A name the catalog does not know is rejected, so the two cannot drift apart."""
    monkeypatch.setattr(sys, "argv", ["run.py", f"--{field}", "not-a-model"])
    with pytest.raises(SystemExit):
        session.resolve()

    assert session.FIELDS[field] is registry
    assert registry, f"{field} has no implementations"


def test_every_catalogued_model_can_be_named(monkeypatch):
    """Every entry in the real catalog is reachable from the command line, whichever provider it came from."""
    argv = ["run.py", *HEADLESS]
    for field, registry in session.FIELDS.items():
        argv += [f"--{field}", sorted(registry)[-1]]
    monkeypatch.setattr(sys, "argv", argv)
    _expect_no_dialog(monkeypatch)

    run = session.resolve()

    for field, registry in session.FIELDS.items():
        assert getattr(run, field) == sorted(registry)[-1]


def test_an_unknown_transport_is_rejected(monkeypatch):
    """The transport flag is held to the same registry as the models."""
    monkeypatch.setattr(sys, "argv", ["run.py", "--transport", "carrier-pigeon"])
    with pytest.raises(SystemExit):
        session.resolve()


def test_vision_is_on_unless_the_command_line_takes_it_away(monkeypatch, catalogue):
    """Only some conditions give the agent eyes, so the camera subscription is one flag and not a code change."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    _expect_no_dialog(monkeypatch)

    monkeypatch.setattr(sys, "argv", ["run.py", *HEADLESS])
    assert session.resolve().vision is True

    monkeypatch.setattr(sys, "argv", ["run.py", *HEADLESS, "--no-vision"])
    assert session.resolve().vision is False


def test_the_participant_id_is_stored_in_its_canonical_form(monkeypatch, catalogue):
    """'p4' and 'P04' name the same participant, so both are written as P04 and land in the same log series."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    monkeypatch.setattr(sys, "argv", ["run.py", "--participant", "p4", "--language", "en", "--scenario", "chat"])
    _expect_no_dialog(monkeypatch)

    assert session.resolve().participant == "P04"


def test_an_id_that_cannot_name_a_file_is_refused_on_the_command_line(monkeypatch, catalogue):
    """The ID becomes the log's file name, so one that cannot be a file name never starts a session."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    monkeypatch.setattr(sys, "argv", ["run.py", "--participant", "a/b", "--language", "en", "--scenario", "chat"])
    _expect_no_dialog(monkeypatch)

    with pytest.raises(SystemExit):
        session.resolve()


def test_a_voice_that_cannot_speak_the_language_is_refused(monkeypatch):
    """Kokoro has no German voice, so a German session with Kokoro stops at the command line rather than speaking English."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "--participant", "P04", "--language", "de", "--scenario", "chat", "--stt", "voxtral", "--llm", "mistral-small", "--tts", "kokoro"],
    )
    _expect_no_dialog(monkeypatch)

    with pytest.raises(SystemExit):
        session.resolve()


def test_the_dialog_is_given_the_same_check(monkeypatch, catalogue):
    """The dialog refuses what the command line refuses, so the two ways in cannot disagree about what makes a session."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    monkeypatch.setattr(sys, "argv", ["run.py"])
    asked = {}

    def fake_choose(languages, options, defaults, suggested, problem):
        asked["problem"] = problem
        return {**defaults, "participant": suggested[0]}

    monkeypatch.setattr("agent.ui.chooser.choose", fake_choose)
    session.resolve()

    assert asked["problem"] is session.problem


def test_every_voice_states_which_session_languages_it_speaks():
    """A voice missing from the language table would fail at startup, and a language it claims must be one a session can be held in."""
    assert catalog.TTS_LANGUAGES.keys() == catalog.TTS.keys()
    for languages in catalog.TTS_LANGUAGES.values():
        assert languages <= LANGUAGES.keys()


def test_the_default_scenario_is_one_the_registry_holds():
    """A default naming a scenario that does not exist would fail only at startup."""
    assert scenarios.DEFAULT in scenarios.SCENARIOS


def test_a_choice_of_scenarios_opens_the_dialog_unless_one_is_named(monkeypatch, catalogue):
    """With more than one scenario the operator has to pick, and naming one on the command line is that pick."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    monkeypatch.setattr(scenarios, "SCENARIOS", {"chat": None, "lab": None})
    monkeypatch.setattr(scenarios, "DEFAULT", "chat")
    asked = {}
    monkeypatch.setattr("agent.ui.chooser.choose", _accept(asked))

    monkeypatch.setattr(sys, "argv", ["run.py", "--participant", "P04", "--language", "en"])
    session.resolve()
    assert asked["options"]["scenario"] == ["chat", "lab"]

    asked.clear()
    monkeypatch.setattr(sys, "argv", ["run.py", "--participant", "P04", "--language", "en", "--scenario", "lab"])
    assert session.resolve().scenario == "lab"
    assert not asked, "the dialog was opened for a scenario the command line named"


def test_an_unknown_scenario_is_rejected(monkeypatch):
    """The scenario flag is held to the registry, like the models."""
    monkeypatch.setattr(sys, "argv", ["run.py", "--scenario", "not-a-scenario"])
    with pytest.raises(SystemExit):
        session.resolve()
