"""What the agent and the Unity client tell each other outside of audio."""

from typing import Any

from loguru import logger
from pipecat.frames.frames import LLMThoughtEndFrame, LLMThoughtStartFrame, LLMThoughtTextFrame, TTSSpeakFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.frameworks.rtvi.models import ClientMessage
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor

from agent.game import Game
from agent.observability.study_log import StudyLog

# The RTVI client-message type Unity sends a measurement under, as {"t": "metric", "d": {...}}. Its data is logged as sent, so a new metric needs no change here.
METRIC = "metric"

# The RTVI client-message type Unity sends a game snapshot under, as {"t": "game-event", "d": {...}}. Only a scenario with a game takes them.
GAME_EVENT = "game-event"

# The RTVI server-message type the agent sends the session's settings under, as {"t": "session", "d": {...}}.
SESSION = "session"

# The RTVI server-message type the agent sends each finished LLM thought under, as {"t": "thought", "d": {"text": ...}}.
THOUGHT = "thought"


class ThoughtRelay(BaseObserver):
    """Sends the client each LLM thought whole, once it has ended."""

    def __init__(self, rtvi: RTVIProcessor, **kwargs):
        """Relay through the worker's RTVI processor."""
        super().__init__(observe_every_push=False, **kwargs)
        self._rtvi = rtvi
        self._thought: list[str] = []

    async def on_push_frame(self, data: FramePushed):
        """Collect a thought's text between its start and end frames and send it at the end."""
        frame = data.frame
        if isinstance(frame, LLMThoughtStartFrame):
            self._thought = []
        elif isinstance(frame, LLMThoughtTextFrame):
            self._thought.append(frame.text)
        elif isinstance(frame, LLMThoughtEndFrame):
            await self._rtvi.send_server_message({"t": THOUGHT, "d": {"text": "".join(self._thought)}})
            self._thought = []


def attach(worker: PipelineWorker, greeting: str | None, study: StudyLog, settings: dict[str, Any], game: Game | None):
    """Wire the client handshake, the client's messages and the thoughts sent to it, so the agent opens only once a client is there to hear it."""
    worker.add_observer(ThoughtRelay(worker.rtvi))

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
