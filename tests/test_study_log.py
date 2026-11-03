"""The study log: one flushed line per event, each utterance once, totals at the end, and nothing that is audio."""

import json

import pytest

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallResultFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMContextAssistantTurnFrame,
    LLMContextUserTurnFrame,
    LLMThoughtEndFrame,
    LLMThoughtStartFrame,
    LLMThoughtTextFrame,
    MetricsFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection

from agent.config import AUDIO_IN
from agent.observability.study_log import StudyLog

MS = 1_000_000


class _Processor:
    """Stand-in for a pipeline processor, which the study log never looks at."""


SOURCE = _Processor()
DESTINATION = _Processor()


@pytest.fixture
def path(tmp_path):
    """Where the session under test writes its log."""
    return tmp_path / "study" / "P01.jsonl"


def _lines(path) -> list[dict]:
    """Read back every event written so far."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


async def _push(log: StudyLog, frame, ms: int = 0, direction=FrameDirection.DOWNSTREAM):
    """Show the log one frame moving between two processors."""
    await log.on_push_frame(
        FramePushed(source=SOURCE, destination=DESTINATION, frame=frame, direction=direction, timestamp=ms * MS)
    )


async def _broadcast(log: StudyLog, frame_cls, **fields):
    """Show the log both copies of a frame broadcast up and down, as an aggregator sends it."""
    down, up = frame_cls(**fields), frame_cls(**fields)
    down.broadcast_sibling_id, up.broadcast_sibling_id = up.id, down.id
    await _push(log, down)
    await _push(log, up, direction=FrameDirection.UPSTREAM)


def test_an_existing_log_is_never_reopened(path):
    """A second session under the same name would mix two participants' records, so opening one fails instead."""
    StudyLog(path).close()
    with pytest.raises(FileExistsError):
        StudyLog(path)


def test_every_line_is_on_disk_as_soon_as_it_is_written(path):
    """A crash mid-session keeps everything logged before it, so each line is flushed rather than buffered until close."""
    log = StudyLog(path)
    log.write("session_start", participant="P01")

    [line] = _lines(path)
    assert line["event"] == "session_start"
    assert line["participant"] == "P01"
    assert {"ts", "iso", "turn"} <= line.keys()
    log.close()


async def test_each_utterance_is_logged_once(path):
    """An aggregator broadcasts what it wrote to the context both ways, and the log keeps one copy of each."""
    log = StudyLog(path)
    await _broadcast(log, LLMContextUserTurnFrame, text="Hello there", timestamp="t0")
    await _broadcast(log, LLMContextAssistantTurnFrame, text="Hi, welcome.", timestamp="t1")
    log.close()

    lines = _lines(path)[:-1]
    assert [(line["event"], line["text"]) for line in lines] == [
        ("user_transcript", "Hello there"),
        ("assistant_message", "Hi, welcome."),
    ]


async def test_a_thought_is_logged_whole_once_it_ends(path):
    """The LLM's reasoning is part of the record, one line per thought rather than per streamed chunk."""
    log = StudyLog(path)
    await _push(log, LLMThoughtStartFrame())
    await _push(log, LLMThoughtTextFrame(text="Mirko is ready,"))
    await _push(log, LLMThoughtTextFrame(text=" so start the task."))
    await _push(log, LLMThoughtEndFrame())
    log.close()

    lines = _lines(path)[:-1]
    assert [(line["event"], line["text"]) for line in lines] == [("llm_thought", "Mirko is ready, so start the task.")]


async def test_audio_never_reaches_the_log(path):
    """Raw audio is never written to disk, so an audio frame leaves no line."""
    log = StudyLog(path)
    await _push(log, InputAudioRawFrame(audio=b"\x00" * 960, sample_rate=AUDIO_IN, num_channels=1))
    log.close()

    assert [line["event"] for line in _lines(path)] == ["session_end"]


async def test_a_tool_call_is_logged_with_its_arguments_and_result(path):
    """What the agent did on its own initiative is part of the record."""
    log = StudyLog(path)
    await _push(
        log,
        FunctionCallResultFrame(function_name="look", tool_call_id="1", arguments={"at": "cube"}, result="a red cube"),
    )
    log.close()

    line = _lines(path)[0]
    assert (line["event"], line["name"], line["arguments"], line["result"]) == (
        "tool_call",
        "look",
        {"at": "cube"},
        "a red cube",
    )


async def test_usage_is_summed_into_the_session_totals(path):
    """Tokens and synthesised characters add up across every metrics frame and arrive in session_end."""
    log = StudyLog(path)
    usage = LLMTokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    for _ in range(2):
        await _push(
            log,
            MetricsFrame(
                data=[
                    LLMUsageMetricsData(processor="llm", value=usage),
                    TTSUsageMetricsData(processor="tts", value=30),
                ]
            ),
        )
    log.close()

    end = _lines(path)[-1]
    assert end["event"] == "session_end"
    assert (end["prompt_tokens"], end["completion_tokens"], end["tts_characters"]) == (200, 40, 60)


async def test_a_barge_in_is_timed_from_the_participant_speaking_to_the_agent_falling_silent(path):
    """Interruption latency runs from the participant starting over the agent to the agent stopping."""
    log = StudyLog(path)
    await _push(log, BotStartedSpeakingFrame(), ms=0)
    await _push(log, VADUserStartedSpeakingFrame(), ms=1000)
    await _push(log, InterruptionFrame(), ms=1050)
    await _push(log, BotStoppedSpeakingFrame(), ms=1180)
    log.close()

    line = _lines(path)[0]
    assert (line["event"], line["seconds"]) == ("interruption_latency", 0.18)


async def test_speech_over_the_agent_that_does_not_interrupt_it_is_not_timed(path):
    """Without an interruption the agent stops on its own, and that gap measures nothing."""
    log = StudyLog(path)
    await _push(log, BotStartedSpeakingFrame(), ms=0)
    await _push(log, VADUserStartedSpeakingFrame(), ms=1000)
    await _push(log, BotStoppedSpeakingFrame(), ms=3000)
    log.close()

    assert [line["event"] for line in _lines(path)] == ["session_end"]


def test_closing_twice_writes_one_session_end(path):
    """The entrypoint closes the log on every way out, so a second close must not add a line or fail."""
    log = StudyLog(path)
    log.close()
    log.close()

    assert [line["event"] for line in _lines(path)] == ["session_end"]


def test_the_log_brings_the_trackers_it_reads_from(path):
    """Turns and latency come from pipecat's own observers, which only report when the worker runs them too."""
    log = StudyLog(path)
    assert log.observers[0] is log
    assert len(log.observers) == 3
    log.close()
