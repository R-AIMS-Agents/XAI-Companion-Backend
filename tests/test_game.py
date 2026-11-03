"""Game events: the newest snapshot in the context, when a reaction makes the agent speak, wait, interrupt or stay silent, and the intro that holds every reaction until the task starts."""

import asyncio
import json

import pytest

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMMessagesTransformFrame,
    LLMRunFrame,
    LLMTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from agent import game as game_module
from agent.game import HEADER, STARTED, Game, Reaction
from agent.observability.study_log import StudyLog

GRACE_S = 0.01

# Long enough for the grace period to pass and the queued run to land.
SETTLE_S = 0.05

# An event timeout far enough above Windows' 15 ms timer resolution to tell before from after.
TIMEOUT_S = 0.1


class _Processor:
    """Stand-in for a pipeline processor, which the game never looks at."""


class _Worker:
    """Stand-in for the worker: applies context transforms as the user aggregator would, and records everything the game queued."""

    def __init__(self):
        """Start from a context holding only the system prompt."""
        self.messages = [{"role": "system", "content": "You are a tutor."}]
        self.queued = []

    async def queue_frames(self, frames):
        """Record the frames and apply any context transform among them."""
        for frame in frames:
            if isinstance(frame, LLMMessagesTransformFrame):
                self.messages = frame.transform(self.messages)
        self.queued.extend(frames)

    def runs(self) -> int:
        """How many times the game has asked the LLM to run."""
        return sum(isinstance(frame, LLMRunFrame) for frame in self.queued)

    def snapshots(self) -> list[dict]:
        """The snapshots the context holds, oldest first."""
        return [
            json.loads(m["content"].removeprefix(HEADER))
            for m in self.messages
            if m["content"].startswith(HEADER)
        ]


def _snapshot(event: str, **fields) -> dict:
    """A game snapshot naming its event."""
    return {"event": event, **fields}


class _Call:
    """Stand-in for a function call's parameters, recording the result the handler hands back."""

    def __init__(self):
        """Start with no result."""
        self.results = []

    async def result_callback(self, result):
        """Record the result."""
        self.results.append(result)


def _table(snapshot: dict) -> Reaction:
    """A reaction table where the event name is the reaction, so each test states what it exercises."""
    return Reaction(snapshot["event"])


@pytest.fixture
def worker():
    """The stand-in worker the game queues into."""
    return _Worker()


@pytest.fixture
def study(tmp_path):
    """A real study log in a temporary folder."""
    log = StudyLog(tmp_path / "P01.jsonl")
    yield log
    log.close()


@pytest.fixture
def game(monkeypatch, worker, study):
    """A game whose grace period is short enough to wait out in a test."""
    monkeypatch.setattr(game_module, "GRACE_S", GRACE_S)
    return Game(_table, worker.queue_frames, study)


@pytest.fixture
def intro(monkeypatch, worker, study):
    """A game that opened with a greeting and holds every reaction until the task starts."""
    monkeypatch.setattr(game_module, "GRACE_S", GRACE_S)
    return Game(_table, worker.queue_frames, study, intro=True)


@pytest.fixture
async def opened(game, worker):
    """A game past its opening, with the queue cleared, so a test sees only what its own events cause."""
    await game.receive(_snapshot("silent", index=0))
    await asyncio.sleep(SETTLE_S)
    worker.queued.clear()
    return game


async def _push(game: Game, frame):
    """Show the game one frame moving through the pipeline."""
    await game.on_push_frame(
        FramePushed(
            source=_Processor(),
            destination=_Processor(),
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
        )
    )


async def test_the_first_snapshot_opens_the_conversation(game, worker, study, tmp_path):
    """Whatever its event, the session's first snapshot runs the LLM, so the agent opens once it knows the game's state."""
    await game.receive(_snapshot("silent"))
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 1
    line = json.loads((tmp_path / "P01.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (line["event"], line["reaction"], line["data"]) == ("game_event", "opening", {"event": "silent"})


async def test_a_silent_event_only_updates_the_context(opened, worker):
    """A silent event changes what the agent knows and nothing it does."""
    await opened.receive(_snapshot("silent", index=1))
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 0
    assert worker.snapshots() == [_snapshot("silent", index=1)]


async def test_only_the_newest_snapshot_stays_in_the_context(opened, worker):
    """Each snapshot is the full state, so an older one is only noise, and the newest one sits last."""
    for index in range(1, 4):
        await opened.receive(_snapshot("silent", index=index))

    assert worker.snapshots() == [_snapshot("silent", index=3)]
    assert worker.messages[-1]["role"] == "developer"


async def test_a_reaction_runs_at_once_when_the_agent_is_idle(opened, worker):
    """With nobody speaking and no reply underway, the agent reacts after the grace period."""
    await opened.receive(_snapshot("when_idle"))
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 1


async def test_a_reaction_waits_while_the_agent_speaks(opened, worker):
    """The agent finishes what it is saying before it reacts."""
    await _push(opened, BotStartedSpeakingFrame())
    await opened.receive(_snapshot("when_idle"))
    await asyncio.sleep(SETTLE_S)
    assert worker.runs() == 0

    await _push(opened, BotStoppedSpeakingFrame())
    await asyncio.sleep(SETTLE_S)
    assert worker.runs() == 1


async def test_events_while_busy_collapse_into_one_run(opened, worker):
    """Several events during one utterance get one reaction, on the newest snapshot."""
    await _push(opened, BotStartedSpeakingFrame())
    for index in range(3):
        await opened.receive(_snapshot("when_idle", index=index))
    await _push(opened, BotStoppedSpeakingFrame())
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 1
    assert worker.snapshots() == [_snapshot("when_idle", index=2)]


async def test_a_reply_not_yet_heard_keeps_the_agent_busy(opened, worker):
    """Between the LLM finishing and the voice starting, the agent is still about to speak, so a reaction waits for it."""
    await _push(opened, LLMContextFrame(context=LLMContext()))
    await _push(opened, LLMTextFrame(text="Well done."))
    await _push(opened, LLMFullResponseEndFrame())
    await opened.receive(_snapshot("when_idle"))
    await asyncio.sleep(SETTLE_S)
    assert worker.runs() == 0

    await _push(opened, BotStartedSpeakingFrame())
    await _push(opened, BotStoppedSpeakingFrame())
    await asyncio.sleep(SETTLE_S)
    assert worker.runs() == 1


async def test_a_reply_with_nothing_to_say_frees_the_agent(opened, worker):
    """A reply with no text is never heard, so the agent is idle again once the LLM finishes."""
    await _push(opened, LLMContextFrame(context=LLMContext()))
    await opened.receive(_snapshot("when_idle"))
    await _push(opened, LLMFullResponseEndFrame())
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 1


async def test_a_user_turn_after_the_snapshot_settles_the_reaction(opened, worker):
    """The participant's own turn runs the LLM on a context that already holds the snapshot, so a second run would answer it twice."""
    await _push(opened, UserStartedSpeakingFrame())
    await opened.receive(_snapshot("when_idle"))
    await _push(opened, UserStoppedSpeakingFrame())
    await _push(opened, LLMContextFrame(context=LLMContext()))
    await _push(opened, LLMFullResponseEndFrame())
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 0


async def test_a_run_begun_before_the_snapshot_entered_does_not_settle_it(opened, worker):
    """A reply built on the context before the snapshot arrived knows nothing of it, so the reaction still follows."""
    earlier = LLMContextFrame(context=LLMContext())
    await opened.receive(_snapshot("when_idle"))
    await _push(opened, earlier)
    await _push(opened, LLMFullResponseEndFrame())
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 1


async def test_a_participant_who_stops_without_a_turn_is_still_answered(opened, worker):
    """When the participant stops without anything reaching the LLM, the held reaction runs after the grace period."""
    await _push(opened, UserStartedSpeakingFrame())
    await opened.receive(_snapshot("when_idle"))
    await _push(opened, UserStoppedSpeakingFrame())
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 1


async def test_an_interrupt_cuts_the_agent_off(opened, worker):
    """An interrupting event stops the agent mid-sentence and runs the LLM on the new snapshot at once."""
    await _push(opened, BotStartedSpeakingFrame())
    await opened.receive(_snapshot("interrupt"))

    assert [type(frame) for frame in worker.queued] == [InterruptionFrame, LLMMessagesTransformFrame, LLMRunFrame]
    assert worker.snapshots() == [_snapshot("interrupt")]


async def test_an_interrupt_never_cuts_off_the_participant(opened, worker):
    """While the participant speaks, an interrupting event waits like any other."""
    await _push(opened, UserStartedSpeakingFrame())
    await opened.receive(_snapshot("interrupt"))
    assert not any(isinstance(frame, InterruptionFrame) for frame in worker.queued)

    await _push(opened, UserStoppedSpeakingFrame())
    await asyncio.sleep(SETTLE_S)
    assert worker.runs() == 1


async def test_every_snapshot_is_written_to_the_study_log_with_its_reaction(opened, tmp_path):
    """The analysis reads which events arrived and what each made the agent do."""
    await opened.receive(_snapshot("silent", index=1))
    await opened.receive(_snapshot("interrupt", index=2))

    lines = [json.loads(line) for line in (tmp_path / "P01.jsonl").read_text(encoding="utf-8").splitlines()]
    events = [(line["reaction"], line["data"]["index"]) for line in lines if line["event"] == "game_event"]
    assert events == [("opening", 0), ("silent", 1), ("interrupt", 2)]


async def test_an_event_nothing_follows_expires_from_the_context(monkeypatch, opened, worker):
    """After the timeout the state stays but the event and detail are cleared, without the agent speaking about it."""
    monkeypatch.setattr(game_module, "EVENT_TIMEOUT_S", TIMEOUT_S)
    await opened.receive(_snapshot("silent", index=1, detail={"flask": "beaker"}))
    await asyncio.sleep(TIMEOUT_S / 2)
    assert worker.snapshots() == [_snapshot("silent", index=1, detail={"flask": "beaker"})]

    await asyncio.sleep(TIMEOUT_S)
    assert worker.snapshots() == [{"event": None, "index": 1, "detail": None}]
    assert worker.runs() == 0


async def test_a_new_event_starts_the_timeout_over(monkeypatch, opened, worker):
    """Only the newest event counts, so its timeout runs from when it arrived."""
    monkeypatch.setattr(game_module, "EVENT_TIMEOUT_S", TIMEOUT_S)
    await opened.receive(_snapshot("silent", index=1))
    await asyncio.sleep(TIMEOUT_S * 0.6)
    await opened.receive(_snapshot("silent", index=2))
    await asyncio.sleep(TIMEOUT_S * 0.6)

    assert worker.snapshots() == [_snapshot("silent", index=2)]


async def test_an_event_still_awaiting_its_reaction_does_not_expire(monkeypatch, opened, worker):
    """While the agent is busy the reaction is held, and it has to run on the event it is a reaction to."""
    monkeypatch.setattr(game_module, "EVENT_TIMEOUT_S", TIMEOUT_S)
    await _push(opened, BotStartedSpeakingFrame())
    await opened.receive(_snapshot("when_idle", index=1))
    await asyncio.sleep(TIMEOUT_S * 1.3)
    assert worker.snapshots() == [_snapshot("when_idle", index=1)]

    await _push(opened, BotStoppedSpeakingFrame())
    await asyncio.sleep(TIMEOUT_S * 0.4)
    assert worker.runs() == 1
    assert worker.snapshots() == [_snapshot("when_idle", index=1)]


async def test_the_intro_holds_every_event_and_keeps_only_the_newest_snapshot(intro, worker, tmp_path):
    """The participant can play around before the task starts without the agent reacting, while it still knows the current state."""
    await intro.receive(_snapshot("when_idle", index=0))
    await intro.receive(_snapshot("interrupt", index=1))
    await asyncio.sleep(SETTLE_S)

    assert worker.runs() == 0
    assert not any(isinstance(frame, InterruptionFrame) for frame in worker.queued)
    assert worker.snapshots() == [_snapshot("interrupt", index=1)]
    lines = [json.loads(line) for line in (tmp_path / "P01.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["reaction"] for line in lines if line["event"] == "game_event"] == ["intro", "intro"]


async def test_starting_the_task_hands_the_reaction_table_back(intro, worker):
    """Once the agent starts the task, events react as their table says, with no second opening."""
    call = _Call()
    await intro.receive(_snapshot("when_idle", index=0))
    await intro.start_task(call)
    await intro.receive(_snapshot("silent", index=1))
    await asyncio.sleep(SETTLE_S)
    assert call.results == [STARTED]
    assert worker.runs() == 0

    await intro.receive(_snapshot("when_idle", index=2))
    await asyncio.sleep(SETTLE_S)
    assert worker.runs() == 1


async def test_starting_the_task_twice_changes_nothing(intro, worker):
    """A second call from the LLM is answered like the first and leaves the game as it was."""
    first, second = _Call(), _Call()
    await intro.start_task(first)
    await intro.start_task(second)
    await intro.receive(_snapshot("silent"))
    await asyncio.sleep(SETTLE_S)

    assert first.results == second.results == [STARTED]
    assert worker.runs() == 0
