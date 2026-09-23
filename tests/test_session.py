"""Session resolution: what the command line settles, what the dialog is asked, and what neither has to."""

import sys
import tkinter as tk

import pytest

import agent.ui
from agent import session
from agent.services import catalog


def _stub(config):
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

    return use


def _expect_no_dialog(monkeypatch):
    """Arrange for an opened dialog to be an import error rather than a window."""
    monkeypatch.delitem(sys.modules, "agent.ui.chooser", raising=False)
    monkeypatch.delattr(agent.ui, "chooser", raising=False)


def test_a_complete_command_line_needs_no_dialog(monkeypatch, catalogue):
    """Naming every model resolves the session without ever importing the chooser, which is the headless path."""
    catalogue(stt=["voxtral", "whisper"], llm=["small", "medium"], tts=["flash", "kokoro"])
    monkeypatch.setattr(
        sys, "argv", ["run.py", "--stt", "whisper", "--llm", "medium", "--tts", "kokoro"]
    )
    _expect_no_dialog(monkeypatch)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("whisper", "medium", "kokoro")
    assert run.transport == "livekit"
    assert "agent.ui.chooser" not in sys.modules


def test_a_sole_implementation_is_settled_without_asking(monkeypatch, catalogue):
    """A field with one implementation has nothing to decide, so a bare command line opens no dialog."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash"])
    monkeypatch.setattr(sys, "argv", ["run.py"])
    _expect_no_dialog(monkeypatch)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "small", "flash")
    assert "agent.ui.chooser" not in sys.modules


def test_the_dialog_opens_on_the_stated_default(monkeypatch, catalogue):
    """The default is the one named in the catalog, not whichever implementation happens to sort first."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["aaa-sorts-first", "the-default"])
    monkeypatch.setattr(sys, "argv", ["run.py"])
    asked = {}

    def fake_choose(options, defaults):
        """Accept whatever the dialog was preselected to, as a person hitting Start would."""
        asked["defaults"] = defaults
        return dict(defaults)

    monkeypatch.setattr("agent.ui.chooser.choose", fake_choose)
    run = session.resolve()

    assert asked["defaults"]["tts"] == "the-default"
    assert run.tts == "the-default"


def test_the_real_catalog_defaults_to_the_documented_stack(monkeypatch):
    """The stack a bare run uses is the one the project settled on, whatever else the catalog gains."""
    monkeypatch.setattr(sys, "argv", ["run.py"])

    def fake_choose(options, defaults):
        """Accept the preselection, standing in for a person hitting Start."""
        return dict(defaults)

    monkeypatch.setattr("agent.ui.chooser.choose", fake_choose)
    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "mistral-small", "elevenlabs-flash")


@pytest.mark.parametrize("field", ["stt", "llm", "tts"])
def test_every_default_is_an_implementation_the_catalog_holds(field):
    """A default naming a model that does not exist would fail only at startup, and only for that field."""
    assert catalog.DEFAULTS[field] in session.FIELDS[field]


def test_a_real_choice_opens_the_dialog(monkeypatch, catalogue):
    """A second implementation makes one field a genuine choice, and that is what the dialog is for."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash", "kokoro"])
    monkeypatch.setattr(sys, "argv", ["run.py"])
    asked = {}

    def fake_choose(options, defaults):
        """Record what the chooser was asked and answer with the last option of each field."""
        asked["options"] = options
        asked["defaults"] = defaults
        return {field: choices[-1] for field, choices in options.items()}

    monkeypatch.setattr("agent.ui.chooser.choose", fake_choose)
    run = session.resolve()

    # Every field arrives preselected and every field is offered, so the dialog reads as the whole session.
    assert asked["defaults"] == {"stt": "voxtral", "llm": "small", "tts": "kokoro"}
    assert asked["options"] == {"stt": ["voxtral"], "llm": ["small"], "tts": ["flash", "kokoro"]}
    assert run.tts == "kokoro"


def test_naming_the_only_real_choice_settles_it(monkeypatch, catalogue):
    """Naming the one field that has a choice leaves nothing to ask, so the dialog stays shut."""
    catalogue(stt=["voxtral"], llm=["small"], tts=["flash", "kokoro"])
    monkeypatch.setattr(sys, "argv", ["run.py", "--tts", "kokoro"])
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
    argv = ["run.py"]
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
