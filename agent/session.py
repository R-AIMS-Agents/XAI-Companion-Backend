"""What one run of the agent is made of, and how the operator settles it before the pipeline starts."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from pipecat.transports.base_transport import BaseTransport

from agent.config import Config
from agent.services import catalog
from agent.transports import livekit

TRANSPORTS: dict[str, Callable[[Config, bool], BaseTransport]] = {"livekit": livekit.create}

# The catalog is the single source of the model choices, so a new entry reaches the command line and the dialog at once.
FIELDS = {"stt": catalog.STT, "llm": catalog.LLM, "tts": catalog.TTS}


@dataclass(frozen=True)
class Session:
    """The choices one run is made with, settled before anything is built."""

    transport: str
    vision: bool
    stt: str
    llm: str
    tts: str


def _parse_args() -> argparse.Namespace:
    """Read the command line, leaving unset any model the operator did not name."""
    parser = argparse.ArgumentParser(description="Run the AI-Companion agent.")
    parser.add_argument("--transport", choices=sorted(TRANSPORTS), default="livekit")
    parser.add_argument(
        "--vision",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="subscribe to the client's camera track (default: on)",
    )
    for field, registry in FIELDS.items():
        parser.add_argument(
            f"--{field}", choices=sorted(registry), help=f"default: {catalog.DEFAULTS[field]}"
        )
    return parser.parse_args()


def resolve() -> Session:
    """Settle every choice, asking the operator only where more than one implementation exists and none was named."""
    args = _parse_args()
    picks = {field: getattr(args, field) for field in FIELDS}

    # A field with a single implementation has nothing to decide, and a dialog that can only be dismissed teaches the operator to click through the one that later carries the participant.
    undecided = [f for f, pick in picks.items() if pick is None and len(FIELDS[f]) > 1]
    picks = {field: pick or catalog.DEFAULTS[field] for field, pick in picks.items()}

    if undecided:
        from agent.ui import chooser

        # Every field is shown once the dialog opens, so it reads as the session about to run rather than as a partial form.
        options = {field: sorted(registry) for field, registry in FIELDS.items()}
        picks = chooser.choose(options, picks)

    return Session(transport=args.transport, vision=args.vision, **picks)
