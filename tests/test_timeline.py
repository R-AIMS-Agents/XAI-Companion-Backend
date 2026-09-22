"""The Timeline observer: control frames logged as they happen, audio frames summarised per window."""

import pytest
from loguru import logger

from pipecat.frames.frames import InputAudioRawFrame, TextFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection

from agent.config import SAMPLE_RATE
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
OTHER = _Processor("other")


@pytest.fixture
def logs() -> list[str]:
    """Collect what the observer logs during one test."""
    lines: list[str] = []
    sink_id = logger.add(lines.append, format="{message}", level="INFO")
    yield lines
    logger.remove(sink_id)


def _audio_push(timestamp_ms: int, destination=DESTINATION) -> FramePushed:
    """Build one audio frame transfer, at a chosen moment and on a chosen hop."""
    return FramePushed(
        source=SOURCE,
        destination=destination,
        frame=InputAudioRawFrame(audio=AUDIO, sample_rate=SAMPLE_RATE, num_channels=1),
        direction=FrameDirection.DOWNSTREAM,
        timestamp=timestamp_ms * MS,
    )


async def _push_all(timeline: Timeline, pushes: list[FramePushed]):
    """Feed a run of frame transfers to the observer in order."""
    for push in pushes:
        await timeline.on_push_frame(push)


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


async def test_audio_stays_silent_until_the_window_closes(logs):
    """Audio is far too fast to log frame by frame, so nothing is printed mid-window."""
    timeline = Timeline(window_secs=1.0)
    await _push_all(timeline, [_audio_push(ms) for ms in range(100, 1100, 100)])
    assert logs == []


async def test_window_summarises_count_and_gaps(logs):
    """One summary per window, carrying the frame count and the largest gap in it."""
    timeline = Timeline(window_secs=1.0)
    timestamps = [100, 200, 500, 600, 700, 800, 900, 1000, 1100]
    await _push_all(timeline, [_audio_push(ms) for ms in timestamps])

    assert len(logs) == 1
    summary = logs[0]
    assert f"x{len(timestamps)}" in summary
    assert f"{len(timestamps) * len(AUDIO)} B" in summary
    assert "max 300.0 ms" in summary
    assert "mean 125.0 ms" in summary


async def test_the_window_is_the_largest_gap_not_the_count(logs):
    """A single long silence is what a stutter sounds like, so it must survive the summary."""
    timeline = Timeline(window_secs=1.0)
    await _push_all(timeline, [_audio_push(100), _audio_push(110), _audio_push(1100)])
    assert "max 990.0 ms" in logs[0]


async def test_each_hop_is_summarised_separately(logs):
    """Two hops carrying the same audio are two timelines, not one."""
    timeline = Timeline(window_secs=1.0)
    for ms in [100, 600, 1100]:
        await _push_all(timeline, [_audio_push(ms), _audio_push(ms, destination=OTHER)])

    assert len(logs) == 2
    assert any("source -> destination" in line for line in logs)
    assert any("source -> other" in line for line in logs)


async def test_windows_keep_coming_after_the_first(logs):
    """The observer keeps summarising for as long as the run lasts."""
    timeline = Timeline(window_secs=1.0)
    await _push_all(timeline, [_audio_push(ms) for ms in range(100, 3101, 100)])
    assert len(logs) == 3


async def test_the_first_gap_of_the_run_is_counted(logs):
    """A run whose clock starts at zero still records the gap between its first two frames."""
    timeline = Timeline(window_secs=1.0)
    await _push_all(timeline, [_audio_push(0), _audio_push(100), _audio_push(1000)])
    assert "max 900.0 ms" in logs[0]
    assert "mean 500.0 ms" in logs[0]
