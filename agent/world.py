"""What the agent and the Unity client tell each other outside of audio."""

from typing import Any

from loguru import logger
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.frameworks.rtvi.models import ClientMessage

from agent.game import Game
from agent.observability.study_log import StudyLog

# The RTVI client-message type Unity sends a measurement under, as {"t": "metric", "d": {...}}. Its data is logged as sent, so a new metric needs no change here.
METRIC = "metric"

# The RTVI client-message type Unity sends a game snapshot under, as {"t": "game-event", "d": {...}}. Only a scenario with a game takes them.
GAME_EVENT = "game-event"

# The RTVI server-message type the agent sends the session's settings under, as {"t": "session", "d": {...}}.
SESSION = "session"


def attach(worker: PipelineWorker, greeting: str | None, study: StudyLog, settings: dict[str, Any], game: Game | None):
    """Wire the client handshake and the client's messages, so the agent opens only once a client is there to hear it."""

    # The worker answers bot-ready on this event itself, so a second handler here would put two of them on the wire. Handlers run as separate tasks, so the settings and bot-ready reach the client in either order.
    @worker.rtvi.event_handler("on_client_ready")
    async def opening(rtvi):
        """Tell the client the session's settings, then speak the scenario's fixed greeting if it has one, so every session opens with the same words."""
        version = ".".join(str(part) for part in rtvi.client_version)
        logger.info(f"Client ready, RTVI {version}")
        study.write("client_ready", rtvi_version=version)
        await rtvi.send_server_message({"t": SESSION, "d": settings})
        if greeting is not None:
            await worker.queue_frame(TTSSpeakFrame(text=greeting))

    @worker.rtvi.event_handler("on_client_message")
    async def message(rtvi, message: ClientMessage):
        """Log a client metric to the study log as sent and hand a game snapshot to the game; any other message type is not part of the contract."""
        if message.type == METRIC:
            study.write("client_metric", data=message.data)
        elif message.type == GAME_EVENT and game is not None:
            await game.receive(message.data)
        else:
            logger.warning(f"Unhandled client message type '{message.type}'")
