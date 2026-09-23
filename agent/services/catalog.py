"""The set of model services a session can be assembled from, one name per implementation.

Every factory imports its provider inside the function, so selecting one model never loads another's dependencies.
"""

from collections.abc import Callable

from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService

from agent.config import Config

STT_MODEL = "voxtral-mini-realtime-latest"
LLM_MODEL = "mistral-small-latest"
TTS_MODEL = "eleven_flash_v2_5"

# ElevenLabs' premade "Rachel". Voice becomes a study condition later, at which point it moves into the session.
TTS_VOICE = "21m00Tcm4TlvDq8ikWAM"


def _demand(value: str | None, name: str) -> str:
    """Return a credential the chosen service cannot run without, refusing to start when it is missing."""
    if not value:
        raise RuntimeError(f"{name} is not set.")
    return value


def _voxtral(config: Config) -> STTService:
    """Build Mistral's Voxtral realtime transcription service."""
    from pipecat.services.mistral.stt import MistralSTTService

    return MistralSTTService(
        api_key=_demand(config.mistral_api_key, "MISTRAL_API_KEY"),
        settings=MistralSTTService.Settings(model=STT_MODEL),
    )


def _mistral_small(config: Config) -> LLMService:
    """Build Mistral's small chat model."""
    from pipecat.services.mistral.llm import MistralLLMService

    return MistralLLMService(
        api_key=_demand(config.mistral_api_key, "MISTRAL_API_KEY"),
        settings=MistralLLMService.Settings(model=LLM_MODEL),
    )


def _elevenlabs_flash(config: Config) -> TTSService:
    """Build ElevenLabs' low latency streaming voice."""
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    return ElevenLabsTTSService(
        api_key=_demand(config.elevenlabs_api_key, "ELEVENLABS_API_KEY"),
        settings=ElevenLabsTTSService.Settings(model=TTS_MODEL, voice=TTS_VOICE),
    )


STT: dict[str, Callable[[Config], STTService]] = {"voxtral": _voxtral}
LLM: dict[str, Callable[[Config], LLMService]] = {"mistral-small": _mistral_small}
TTS: dict[str, Callable[[Config], TTSService]] = {"elevenlabs-flash": _elevenlabs_flash}
