"""Configuration for the agent, read from the environment once at startup."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# LiveKit publishes Opus at 48 kHz, so the pipeline runs at 48 kHz too and nothing resamples on the way through.
SAMPLE_RATE = 48000


@dataclass(frozen=True)
class Config:
    """Everything the agent needs to reach the LiveKit server and join a room."""

    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    room: str


def _required(name: str) -> str:
    """Read one environment variable, refusing to start when it is missing or empty."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def load() -> Config:
    """Load the configuration from .env and the environment."""
    load_dotenv()
    return Config(
        livekit_url=_required("LIVEKIT_URL"),
        livekit_api_key=_required("LIVEKIT_API_KEY"),
        livekit_api_secret=_required("LIVEKIT_API_SECRET"),
        room=_required("LIVEKIT_ROOM"),
    )
