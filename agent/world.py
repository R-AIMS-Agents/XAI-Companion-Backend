"""What the agent and the Unity client tell each other outside of audio."""

from loguru import logger
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.worker import PipelineWorker

from agent.prompt import GREETING


def attach(worker: PipelineWorker):
    """Wire the client handshake, so the agent opens the conversation only once a client is there to hear it."""

    # The worker answers bot-ready on this event itself, so a second handler here would put two of them on the wire.
    @worker.rtvi.event_handler("on_client_ready")
    async def opening(rtvi):
        """Speak the fixed greeting, so every session opens with the same words."""
        logger.info(f"Client ready, RTVI {'.'.join(str(part) for part in rtvi.client_version)}")
        await worker.queue_frame(TTSSpeakFrame(text=GREETING))
