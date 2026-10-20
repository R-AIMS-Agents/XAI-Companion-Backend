"""The Timeline observer: each control frame logged once as it first moves, audio frames not at all."""

import pytest
from loguru import logger

from pipecat.frames.frames import InputAudioRawFrame, TextFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection

from agent.config import AUDIO_IN
from agent.observability.timeline import Timeline

MS = 1_000_000
AUDIO = b"\x00" * 960


class _Processor:
    """Stand-in for a pipeline processor. The observer only ever prints its name."""

    def __init__(self, name: str):
        """Name the stand-in, since the name is all the observer ever reads."""
        self._name = name

    def __str__(self) -> str:
        """Render as the processor name the observer prints in a hop."""
        return self._name


SOURCE = _Processor("source")
DESTINATION = _Processor("destination")


@pytest.fixture
def logs() -> list[str]:
    """Collect what the observer logs during one test."""
    lines: list[str] = []
    sink_id = logger.add(lines.append, format="{message}", level="INFO")
    yield lines
    logger.remove(sink_id)


def _audio_push(timestamp_ms: int) -> FramePushed:
    """Build one audio frame transfer at a chosen moment."""
    return FramePushed(
        source=SOURCE,
        destination=DESTINATION,
        frame=InputAudioRawFrame(audio=AUDIO, sample_rate=AUDIO_IN, num_channels=1),
        direction=FrameDirection.DOWNSTREAM,
        timestamp=timestamp_ms * MS,
    )


async def test_control_frames_are_logged_immediately(logs):
    """A control frame is rare enough to print on its own line the moment it moves."""
    timeline = Timeline()
    await timeline.on_push_frame(
        FramePushed(
            source=SOURCE,
            destination=DESTINATION,
            frame=TextFrame(text="hello"),
            direction=FrameDirection.DOWNSTREAM,
            timestamp=250 * MS,
        )
    )
    assert len(logs) == 1
    assert "source -> destination" in logs[0]
    assert "0.250s" in logs[0]


async def test_audio_frames_are_not_logged(logs):
    """Audio frames pass through without leaving a line."""
    timeline = Timeline()
    for ms in range(100, 1100, 100):
        await timeline.on_push_frame(_audio_push(ms))
    assert logs == []


def test_a_frame_is_observed_only_at_its_first_hop():
    """The observer asks pipecat to report each frame at its first push only, so further hops add no lines."""
    assert Timeline().observe_every_push is False
