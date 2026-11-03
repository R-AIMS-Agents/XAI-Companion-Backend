"""The frame pipeline. Receives its transport, its services, its prompt and its tools, and constructs none of them."""

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
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
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.types import NOT_GIVEN

from agent.vad_fallback import VADFallback, VADFallbackStopStrategy


def build(
    transport: BaseTransport,
    stt: STTService,
    llm: LLMService,
    tts: TTSService,
    system_prompt: str,
    tools: list[FunctionSchema],
) -> Pipeline:
    """Assemble the pipeline. The only place it is assembled."""
    context = LLMContext(messages=[{"role": "system", "content": system_prompt}], tools=tools or NOT_GIVEN)

    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3()),
                    VADFallbackStopStrategy(),
                ]
            ),
            # Held muted from connect until the greeting finishes, so nothing said before or during it reaches the LLM.
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )

    return Pipeline(
        [
            transport.input(),
            stt,
            VADFallback(),
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )
