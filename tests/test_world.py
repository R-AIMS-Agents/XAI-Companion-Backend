"""What the agent tells the client outside of audio: each LLM thought, sent whole."""

from pipecat.frames.frames import LLMThoughtEndFrame, LLMThoughtStartFrame, LLMThoughtTextFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection

from agent.world import THOUGHT, ThoughtRelay


class _RTVI:
    """Stand-in for the worker's RTVI processor, recording the server messages sent through it."""

    def __init__(self):
        """Start with nothing sent."""
        self.sent = []

    async def send_server_message(self, data):
        """Record one server message."""
        self.sent.append(data)


async def _push(relay: ThoughtRelay, frame):
    """Show the relay one frame moving downstream."""
    await relay.on_push_frame(
        FramePushed(source=None, destination=None, frame=frame, direction=FrameDirection.DOWNSTREAM, timestamp=0)
    )


async def test_a_thought_reaches_the_client_whole_once_it_ends():
    """The client gets one server message per thought, not one per streamed chunk."""
    rtvi = _RTVI()
    relay = ThoughtRelay(rtvi)
    await _push(relay, LLMThoughtStartFrame())
    await _push(relay, LLMThoughtTextFrame(text="Ready,"))
    assert rtvi.sent == []
    await _push(relay, LLMThoughtTextFrame(text=" so start."))
    await _push(relay, LLMThoughtEndFrame())
    assert rtvi.sent == [{"t": THOUGHT, "d": {"text": "Ready, so start."}}]
