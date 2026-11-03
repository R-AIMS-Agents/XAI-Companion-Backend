"""The set of model services a session can be assembled from, one name per implementation.

One factory per provider, bound to a model by the registry beneath it, so a further model of a provider already present costs a line.
Every model is pinned to a snapshot, never a moving alias, so a provider cannot swap the model under a running study.
Every factory imports its provider inside the function, so selecting one model never loads another's dependencies.
"""

from collections.abc import Callable
from functools import partial

from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language

from agent.config import Config

# ElevenLabs' premade voices. Voice becomes a study condition later, at which point it moves into the session.
NICHALIA= "XfNU2rGpBa01ckF309OY"


def _demand(value: str | None, name: str) -> str:
    """Return a credential the chosen service cannot run without, refusing to start when it is missing."""
    if not value:
        raise RuntimeError(f"{name} is not set.")
    return value


def _mistral_stt(config: Config, language: Language, model: str) -> STTService:
    """Build one of Mistral's Voxtral realtime transcription models."""
    from pipecat.services.mistral.stt import MistralSTTService

    return MistralSTTService(
        api_key=_demand(config.mistral_api_key, "MISTRAL_API_KEY"),
        settings=MistralSTTService.Settings(model=model, language=language),
    )


def _whisper(config: Config, language: Language, model: str) -> STTService:
    """Build a local faster-whisper model that needs no credential once cached."""
    from pipecat.services.whisper.stt import WhisperSTTService

    return WhisperSTTService(settings=WhisperSTTService.Settings(model=model, language=language))


def _nemotron(config: Config, language: Language) -> STTService:
    """Build Nemotron streaming ASR served by a local NVIDIA NIM container, which needs no credential."""
    from pipecat.services.nvidia.stt import NvidiaSTTService

    return NvidiaSTTService(
        server="localhost:50051",
        use_ssl=False,
        model_function_map={"function_id": "", "model_name": "nemotron-asr-streaming"},
        settings=NvidiaSTTService.Settings(language=language),
    )


def _mistral_llm(config: Config, model: str) -> LLMService:
    """Build one of Mistral's chat models."""
    from pipecat.services.mistral.llm import MistralLLMService

    return MistralLLMService(
        api_key=_demand(config.mistral_api_key, "MISTRAL_API_KEY"),
        settings=MistralLLMService.Settings(model=model),
    )


def _elevenlabs(config: Config, language: Language, model: str, voice: str) -> TTSService:
    """Build one of ElevenLabs' streaming voices."""
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    return ElevenLabsTTSService(
        api_key=_demand(config.elevenlabs_api_key, "ELEVENLABS_API_KEY"),
        settings=ElevenLabsTTSService.Settings(model=model, voice=voice, language=language),
    )


def _kokoro(config: Config, language: Language, voice: str) -> TTSService:
    """Build Kokoro, a local ONNX voice that needs no credential or network access once its model is cached."""
    from pipecat.services.kokoro.tts import KokoroTTSService

    return KokoroTTSService(settings=KokoroTTSService.Settings(voice=voice, language=language))


STT: dict[str, Callable[[Config, Language], STTService]] = {
    "voxtral": partial(_mistral_stt, model="voxtral-mini-transcribe-realtime-3-0"),
    "whisper-turbo": partial(_whisper, model="deepdml/faster-whisper-large-v3-turbo-ct2"),
    "nemotron": _nemotron,
}

LLM: dict[str, Callable[[Config], LLMService]] = {
    "mistral-small": partial(_mistral_llm, model="mistral-small-2603"),
    "mistral-large": partial(_mistral_llm, model="mistral-large-4-0"),
}

TTS: dict[str, Callable[[Config, Language], TTSService]] = {
    "elevenlabs-flash": partial(_elevenlabs, model="eleven_flash_v2_5", voice=NICHALIA),
    "kokoro": partial(_kokoro, voice="af_heart"),
}

# The session languages each voice can speak. Kokoro has no German voice, so a German session refuses it rather than speaking English.
TTS_LANGUAGES = {"elevenlabs-flash": {"en", "de"}, "kokoro": {"en"}}

# What a run uses when the operator names nothing, stated here rather than left to the order the registries happen to be in.
DEFAULTS = {"stt": "nemotron", "llm": "mistral-small", "tts": "elevenlabs-flash"}
