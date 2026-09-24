"""The set of model services a session can be assembled from, one name per implementation.

One factory per provider, bound to a model by the registry beneath it, so a further model of a provider already present costs a line.
Every factory imports its provider inside the function, so selecting one model never loads another's dependencies.
"""

from collections.abc import Callable
from functools import partial

from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService

from agent.config import Config

# ElevenLabs' premade voices. Voice becomes a study condition later, at which point it moves into the session.
NICHALIA= "XfNU2rGpBa01ckF309OY"


def _demand(value: str | None, name: str) -> str:
    """Return a credential the chosen service cannot run without, refusing to start when it is missing."""
    if not value:
        raise RuntimeError(f"{name} is not set.")
    return value


def _mistral_stt(config: Config, model: str) -> STTService:
    """Build one of Mistral's Voxtral realtime transcription models."""
    from pipecat.services.mistral.stt import MistralSTTService

    return MistralSTTService(
        api_key=_demand(config.mistral_api_key, "MISTRAL_API_KEY"),
        settings=MistralSTTService.Settings(model=model),
    )


def _mistral_llm(config: Config, model: str) -> LLMService:
    """Build one of Mistral's chat models."""
    from pipecat.services.mistral.llm import MistralLLMService

    return MistralLLMService(
        api_key=_demand(config.mistral_api_key, "MISTRAL_API_KEY"),
        settings=MistralLLMService.Settings(model=model),
    )


def _elevenlabs(config: Config, model: str, voice: str) -> TTSService:
    """Build one of ElevenLabs' streaming voices."""
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    return ElevenLabsTTSService(
        api_key=_demand(config.elevenlabs_api_key, "ELEVENLABS_API_KEY"),
        settings=ElevenLabsTTSService.Settings(model=model, voice=voice),
    )


def _kokoro(config: Config, voice: str) -> TTSService:
    """Build Kokoro, a local ONNX voice that needs no credential or network access once its model is cached."""
    from pipecat.services.kokoro.tts import KokoroTTSService

    return KokoroTTSService(settings=KokoroTTSService.Settings(voice=voice))


STT: dict[str, Callable[[Config], STTService]] = {
    "voxtral": partial(_mistral_stt, model="voxtral-mini-realtime-latest"),
}

LLM: dict[str, Callable[[Config], LLMService]] = {
    "mistral-small": partial(_mistral_llm, model="mistral-small-latest"),
    "mistral-medium": partial(_mistral_llm, model="mistral-medium-latest"),
}

TTS: dict[str, Callable[[Config], TTSService]] = {
    "elevenlabs-flash": partial(_elevenlabs, model="eleven_flash_v2_5", voice=NICHALIA),
    "kokoro": partial(_kokoro, voice="af_heart"),
}

# What a run uses when the operator names nothing, stated here rather than left to the order the registries happen to be in.
DEFAULTS = {"stt": "voxtral", "llm": "mistral-small", "tts": "elevenlabs-flash"}
