"""Session resolution: the command line settles a run on its own, and the choices come from one place."""

import sys

import pytest

import agent.ui
from agent import session
from agent.services import catalog

FULLY_SPECIFIED = [
    "run.py",
    "--stt",
    "voxtral",
    "--llm",
    "mistral-small",
    "--tts",
    "elevenlabs-flash",
]


def test_a_complete_command_line_needs_no_dialog(monkeypatch):
    """Naming every model resolves the session without ever importing the chooser, which is the headless path."""
    monkeypatch.setattr(sys, "argv", FULLY_SPECIFIED)
    monkeypatch.delitem(sys.modules, "agent.ui.chooser", raising=False)
    monkeypatch.delattr(agent.ui, "chooser", raising=False)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "mistral-small", "elevenlabs-flash")
    assert run.transport == "livekit"
    assert "agent.ui.chooser" not in sys.modules


def test_a_sole_implementation_is_settled_without_asking(monkeypatch):
    """With one implementation per field there is nothing to decide, so a bare command line opens no dialog."""
    monkeypatch.setattr(sys, "argv", ["run.py"])
    monkeypatch.delitem(sys.modules, "agent.ui.chooser", raising=False)
    monkeypatch.delattr(agent.ui, "chooser", raising=False)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "mistral-small", "elevenlabs-flash")
    assert "agent.ui.chooser" not in sys.modules


def test_a_real_choice_opens_the_dialog(monkeypatch):
    """A second implementation makes one field a genuine choice, and that is what the dialog is for."""
    monkeypatch.setitem(catalog.TTS, "kokoro", lambda config: None)
    monkeypatch.setattr(sys, "argv", ["run.py"])
    asked = {}

    def fake_choose(options, defaults):
        """Record what the chooser was asked and answer with the last option of each field."""
        asked["options"] = options
        asked["defaults"] = defaults
        return {field: choices[-1] for field, choices in options.items()}

    monkeypatch.setattr("agent.ui.chooser.choose", fake_choose)
    run = session.resolve()

    # The settled fields arrive already filled in; only the real choice is left open.
    assert asked["defaults"] == {"stt": "voxtral", "llm": "mistral-small", "tts": None}
    assert asked["options"]["tts"] == ["elevenlabs-flash", "kokoro"]
    assert set(asked["options"]) == {"stt", "llm", "tts"}
    assert run.tts == "kokoro"


def test_a_named_model_settles_the_only_real_choice(monkeypatch):
    """Naming the one field that has a choice leaves nothing to ask, so the dialog stays shut."""
    monkeypatch.setitem(catalog.TTS, "kokoro", lambda config: None)
    monkeypatch.setattr(sys, "argv", ["run.py", "--tts", "kokoro"])
    monkeypatch.delitem(sys.modules, "agent.ui.chooser", raising=False)
    monkeypatch.delattr(agent.ui, "chooser", raising=False)

    run = session.resolve()

    assert (run.stt, run.llm, run.tts) == ("voxtral", "mistral-small", "kokoro")
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

    assert sorted(session.FIELDS[field]) == sorted(registry)


def test_an_unknown_transport_is_rejected(monkeypatch):
    """The transport flag is held to the same registry as the models."""
    monkeypatch.setattr(sys, "argv", ["run.py", "--transport", "carrier-pigeon"])
    with pytest.raises(SystemExit):
        session.resolve()
