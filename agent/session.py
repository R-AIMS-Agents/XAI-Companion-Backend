"""What one run of the agent is made of, and how the operator settles it before the pipeline starts."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from pipecat.transports.base_transport import BaseTransport

from agent import nemotron_server, roster, scenarios
from agent.config import LANGUAGES, Config
from agent.services import catalog
from agent.transports import livekit

TRANSPORTS: dict[str, Callable[[Config, bool], BaseTransport]] = {"livekit": livekit.create}

# The catalog is the single source of the model choices, so a new entry reaches the command line and the dialog at once.
FIELDS = {"stt": catalog.STT, "llm": catalog.LLM, "tts": catalog.TTS}

DEFAULT_LANGUAGE = "en"


@dataclass(frozen=True)
class Session:
    """The choices one run is made with, settled before anything is built."""

    transport: str
    vision: bool
    participant: str
    language: str
    scenario: str
    stt: str
    llm: str
    tts: str


def _parser() -> argparse.ArgumentParser:
    """Describe the command line, leaving unset anything the operator may be asked for instead."""
    parser = argparse.ArgumentParser(description="Run the TrIVA agent.")
    parser.add_argument("--transport", choices=sorted(TRANSPORTS), default="livekit")
    parser.add_argument(
        "--vision",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="subscribe to the client's camera track (default: on)",
    )
    parser.add_argument("--participant", help="pseudonymous participant ID, such as P04")
    parser.add_argument("--language", choices=list(LANGUAGES), help=f"default: {DEFAULT_LANGUAGE}")
    parser.add_argument(
        "--scenario", choices=sorted(scenarios.SCENARIOS), help=f"default: {scenarios.DEFAULT}"
    )
    for field, registry in FIELDS.items():
        parser.add_argument(
            f"--{field}", choices=sorted(registry), help=f"default: {catalog.DEFAULTS[field]}"
        )
    return parser


def problem(picks: dict[str, str]) -> str | None:
    """Say what stops these picks from making a session, or return None when they make one."""
    if roster.normalise(picks["participant"]) is None:
        return f"'{picks['participant']}' cannot be a participant ID."
    if picks["language"] not in catalog.TTS_LANGUAGES[picks["tts"]]:
        return f"{picks['tts']} cannot speak {LANGUAGES[picks['language']]}."
    return None


def resolve() -> Session:
    """Settle every choice, asking the operator for whatever the command line left open."""
    parser = _parser()
    args = parser.parse_args()
    picks = {field: getattr(args, field) for field in FIELDS}

    # A model or scenario with a single entry has nothing to decide, but participant and language always need an answer.
    undecided = [f for f, pick in picks.items() if pick is None and len(FIELDS[f]) > 1]
    undecided += [f for f in ("participant", "language") if getattr(args, f) is None]
    if args.scenario is None and len(scenarios.SCENARIOS) > 1:
        undecided.append("scenario")
    picks = {field: pick or catalog.DEFAULTS[field] for field, pick in picks.items()}
    picks = {
        "participant": args.participant or "",
        "language": args.language or DEFAULT_LANGUAGE,
        "scenario": args.scenario or scenarios.DEFAULT,
        **picks,
    }

    if undecided:
        from agent.ui import chooser

        # Every field is shown once the dialog opens, so it reads as the session about to run rather than as a partial form.
        options = {"scenario": sorted(scenarios.SCENARIOS)}
        options |= {field: sorted(registry) for field, registry in FIELDS.items()}
        picks = chooser.choose(
            LANGUAGES, options, picks, [roster.suggest(), roster.TEST], problem, {"stt": nemotron_server.hint}
        )
    elif error := problem(picks):
        parser.error(error)

    picks["participant"] = roster.normalise(picks["participant"])
    return Session(transport=args.transport, vision=args.vision, **picks)
