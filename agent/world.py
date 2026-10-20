"""What the agent and the Unity client tell each other outside of audio."""

from loguru import logger
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.frameworks.rtvi.models import ClientMessage

from agent.observability.study_log import StudyLog

# The RTVI client-message type Unity sends a measurement under, as {"t": "metric", "d": {...}}. Its data is logged as sent, so a new metric needs no change here.
METRIC = "metric"


def attach(worker: PipelineWorker, greeting: str, study: StudyLog):
    """Wire the client handshake and the client's messages, so the agent opens only once a client is there to hear it."""

    # The worker answers bot-ready on this event itself, so a second handler here would put two of them on the wire.
    @worker.rtvi.event_handler("on_client_ready")
    async def opening(rtvi):
        """Speak the fixed greeting, so every session opens with the same words."""
        version = ".".join(str(part) for part in rtvi.client_version)
        logger.info(f"Client ready, RTVI {version}")
        study.write("client_ready", rtvi_version=version)
        await worker.queue_frame(TTSSpeakFrame(text=greeting))

    @worker.rtvi.event_handler("on_client_message")
    async def message(rtvi, message: ClientMessage):
        """Log a client metric to the study log as sent; any other message type is not part of the contract yet."""
        if message.type == METRIC:
            study.write("client_metric", data=message.data)
        else:
            logger.warning(f"Unhandled client message type '{message.type}'")
