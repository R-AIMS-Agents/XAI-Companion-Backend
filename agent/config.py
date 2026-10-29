"""Configuration for the agent, read from the environment once at startup."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Silero VAD and Smart Turn accept 16 kHz only, and the STT wants it too, so the transport resamples once on the way in.
AUDIO_IN = 16000

# LiveKit publishes Opus at 48 kHz and ElevenLabs can synthesise at 48 kHz, so the way out stays native.
AUDIO_OUT = 48000

# The languages a session can be held in, by the code the services take, with the name the prompt uses for each.
LANGUAGES = {"en": "English", "de": "German"}


@dataclass(frozen=True)
class Config:
    """Everything the agent needs to reach the LiveKit server and the model providers."""

    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    room: str
    mistral_api_key: str | None
    elevenlabs_api_key: str | None


def _required(name: str) -> str:
    """Read one environment variable, refusing to start when it is missing or empty."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set.")
    return value


def load() -> Config:
    """Load the configuration from .env and the environment."""
    load_dotenv()
    return Config(
        livekit_url=_required("LIVEKIT_URL"),
        livekit_api_key=_required("LIVEKIT_API_KEY"),
        livekit_api_secret=_required("LIVEKIT_API_SECRET"),
        room=_required("LIVEKIT_ROOM"),
        mistral_api_key=os.environ.get("MISTRAL_API_KEY"),
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY"),
    )
