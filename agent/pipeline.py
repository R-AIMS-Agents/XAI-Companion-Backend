"""The frame pipeline. Receives its transport and its services, and constructs neither."""

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_mute import MuteUntilFirstBotCompleteUserMuteStrategy

from agent.prompt import SYSTEM_PROMPT


def build(
    transport: BaseTransport, stt: STTService, llm: LLMService, tts: TTSService
) -> Pipeline:
    """Assemble the pipeline. The only place it is assembled."""
    context = LLMContext(messages=[{"role": "system", "content": SYSTEM_PROMPT}])

    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            # Held muted from connect until the greeting finishes, so nothing said before or during it reaches the LLM.
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )

    return Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )
